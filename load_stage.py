# load_stage.py - step 1
# Read the two NDJSON files, clean the data, load the staging tables.

import json
from datetime import datetime

from common import (get_connection, create_tables, check_source_files,
                    clean_text, normalize_category, parse_date,
                    parse_timestamp, get_logger,
                    PATIENT_FILE, ALLERGY_FILE, ALERT_FOLDER)

logger = get_logger("load_stage")


def parse_patients(file_path, rejects, warnings):
    patients = []
    seen_ids = []

    f = open(file_path, encoding="utf-8")
    line_no = 0
    for line in f:
        line_no = line_no + 1
        line = line.strip()
        if line == "":
            continue

        # the line must be valid JSON
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            rejects.append((file_path, line_no, "invalid JSON: " + str(e), line))
            continue

        # must be a Patient record
        if rec.get("resourceType") != "Patient":
            rejects.append((file_path, line_no, "not a Patient record", line))
            continue

        # must have an id
        patient_id = clean_text(rec.get("id"))
        if patient_id is None:
            rejects.append((file_path, line_no, "missing id", line))
            continue

        # skip duplicates
        if patient_id in seen_ids:
            rejects.append((file_path, line_no, "duplicate patient id", line))
            continue
        seen_ids.append(patient_id)

        # name: FHIR has a list of names, we take the first one
        family = None
        given = None
        name_list = rec.get("name")
        if name_list is not None and len(name_list) > 0:
            first_name_entry = name_list[0]
            family = clean_text(first_name_entry.get("family"))
            given_list = first_name_entry.get("given")
            if given_list is not None and len(given_list) > 0:
                given = clean_text(" ".join(given_list))

        full_name = None
        if given is not None and family is not None:
            full_name = given + " " + family
        elif given is not None:
            full_name = given
        elif family is not None:
            full_name = family

        # address: also a list, take the first one
        city = None
        state = None
        postal_code = None
        country = None
        address_line = None
        address_list = rec.get("address")
        if address_list is not None and len(address_list) > 0:
            address = address_list[0]
            city = clean_text(address.get("city"))
            state = clean_text(address.get("state"))
            postal_code = clean_text(address.get("postalCode"))
            country = clean_text(address.get("country"))
            line_list = address.get("line")
            if line_list is not None and len(line_list) > 0:
                address_line = clean_text(" ".join(line_list))

        # phone: first telecom entry where system = 'phone'
        phone = None
        telecom_list = rec.get("telecom")
        if telecom_list is not None:
            for entry in telecom_list:
                if entry.get("system") == "phone":
                    phone = clean_text(entry.get("value"))
                    break

        # gender: normalize MALE / Male -> male
        gender = clean_text(rec.get("gender"))
        if gender is not None:
            gender = gender.lower()
        else:
            gender = "unknown"

        birth_date = parse_date(rec.get("birthDate"))

        # non-critical checks: the record still loads, but missing
        # fields are reported in the log + alert file
        non_critical = {"postal_code": postal_code, "birth_date": birth_date,
                        "city": city, "phone": phone}
        for field_name in non_critical:
            if non_critical[field_name] is None:
                warnings.append((file_path, line_no,
                                 "Patient " + patient_id,
                                 field_name + " is missing or invalid"))

        row = (patient_id, full_name, gender, birth_date, address_line,
               city, state, postal_code, country, phone,
               file_path, line_no)
        patients.append(row)

    f.close()
    return patients


def parse_allergies(file_path, rejects, warnings):
    allergies = []
    seen_ids = []

    f = open(file_path, encoding="utf-8")
    line_no = 0
    for line in f:
        line_no = line_no + 1
        line = line.strip()
        if line == "":
            continue

        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            rejects.append((file_path, line_no, "invalid JSON: " + str(e), line))
            continue

        if rec.get("resourceType") != "AllergyIntolerance":
            rejects.append((file_path, line_no, "not an AllergyIntolerance record", line))
            continue

        allergy_id = clean_text(rec.get("id"))
        if allergy_id is None:
            rejects.append((file_path, line_no, "missing id", line))
            continue

        if allergy_id in seen_ids:
            rejects.append((file_path, line_no, "duplicate allergy id", line))
            continue
        seen_ids.append(allergy_id)

        # patient reference concatenated with "/" separator
        # we keep the id part after the "/". if it is missing, the record
        # still loads and will link to the Unknown patient in the fact load.

        patient_id = None
        patient_section = rec.get("patient")
        if patient_section is not None:
            reference = clean_text(patient_section.get("reference"))
            if reference is not None and "/" in reference:
                parts = reference.split("/")
                patient_id = parts[len(parts) - 1]

        # category is a list in FHIR. it can be missing, empty, or contain
        # null / empty / dirty values - we take the first usable entry

        category = None
        category_list = rec.get("category")
        if category_list is not None:
            for value in category_list:
                if clean_text(value) is not None:
                    category = normalize_category(value)
                    break

        # allergen code: first entry of code.coding, display falls back to code.text

        allergen_system = None
        allergen_code = None
        allergen_display = None
        code_section = rec.get("code")
        if code_section is not None:
            coding_list = code_section.get("coding")
            if coding_list is not None and len(coding_list) > 0:
                first_coding = coding_list[0]
                allergen_system = clean_text(first_coding.get("system"))
                allergen_code = clean_text(first_coding.get("code"))
                allergen_display = clean_text(first_coding.get("display"))
            if allergen_display is None:
                allergen_display = clean_text(code_section.get("text"))

        # reaction + severity: not present in the current source files,
        # but FHIR allows them, so we read them if they are there

        reaction_code = None
        reaction_display = None
        severity = None
        reaction_list = rec.get("reaction")
        if reaction_list is not None and len(reaction_list) > 0:
            first_reaction = reaction_list[0]
            severity = clean_text(first_reaction.get("severity"))
            if severity is not None:
                severity = severity.lower()
            manifestation_list = first_reaction.get("manifestation")
            if manifestation_list is not None and len(manifestation_list) > 0:
                coding_list = manifestation_list[0].get("coding")
                if coding_list is not None and len(coding_list) > 0:
                    reaction_code = clean_text(coding_list[0].get("code"))
                    reaction_display = clean_text(coding_list[0].get("display"))

        allergy_type = clean_text(rec.get("type"))
        criticality = clean_text(rec.get("criticality"))
        recorded_date = parse_timestamp(rec.get("recordedDate"))

        # non-critical checks: the record still loads (missing values
        # will map to the Unknown dimension rows), but we report the gaps.

        non_critical = {"category": category, "recorded_date": recorded_date,
                        "criticality": criticality,
                        "allergen_code": allergen_code}
        for field_name in non_critical:
            if non_critical[field_name] is None:
                warnings.append((file_path, line_no,
                                 "Allergy " + allergy_id,
                                 field_name + " is missing or invalid"))

        row = (allergy_id, patient_id, allergy_type, category, criticality,
               allergen_system, allergen_code, allergen_display,
               reaction_code, reaction_display, severity, recorded_date,
               file_path, line_no)
        allergies.append(row)

    f.close()
    return allergies


def write_alert(rejects, warnings):
    # write an alert file so the support team notices the problems.
    # In real time env, this is where an incident would be raised.
    now = datetime.now()
    file_name = ALERT_FOLDER + "/alert_" + now.strftime("%Y%m%d_%H%M%S") + ".txt"
    f = open(file_name, "w", encoding="utf-8")
    f.write("ALERT " + str(now) + "\n")
    f.write(str(len(rejects)) + " critical record(s) rejected, "
            + str(len(warnings)) + " non-critical warning(s)\n\n")

    if len(rejects) > 0:
        f.write("CRITICAL - moved to staging.rejects, not loaded:\n")
        for reject in rejects:
            f.write(reject[0] + " line " + str(reject[1]) + ": " + reject[2] + "\n")
            f.write("  " + reject[3][0:200] + "\n")
        f.write("\n")

    if len(warnings) > 0:
        f.write("NON-CRITICAL - loaded, but fields are missing:\n")
        for warning in warnings:
            f.write(warning[0] + " line " + str(warning[1]) + ": "
                    + warning[2] + " - " + warning[3] + "\n")
    f.close()
    logger.warning("ALERT: %d critical reject(s), %d non-critical warning(s)",
                   len(rejects), len(warnings))
    logger.warning("alert details written to: %s", file_name)


def main():
    logger.info("step 1: staging load started")
    logger.info("patient file: %s", PATIENT_FILE)
    logger.info("allergy file: %s", ALLERGY_FILE)
    check_source_files()

    rejects = []
    warnings = []
    patients = parse_patients(PATIENT_FILE, rejects, warnings)
    allergies = parse_allergies(ALLERGY_FILE, rejects, warnings)
    logger.info("parsed: %d patients, %d allergies, %d rejects, %d warnings",
                len(patients), len(allergies), len(rejects), len(warnings))

    # every non-critical warning also goes to the log file
    for warning in warnings:
        logger.warning("%s line %d: %s - %s",
                       warning[0], warning[1], warning[2], warning[3])

    conn = get_connection()
    try:
        cur = conn.cursor()
        create_tables(cur)

        # staging is emptied and fully reloaded on every run
        cur.execute("TRUNCATE staging.stg_patient")
        cur.execute("TRUNCATE staging.stg_allergy")
        cur.execute("TRUNCATE staging.rejects")

        patient_sql = """
            INSERT INTO staging.stg_patient (
                patient_id, full_name, gender, birth_date, address_line,
                city, state, postal_code, country, phone,
                source_file, source_line)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.executemany(patient_sql, patients)

        allergy_sql = """
            INSERT INTO staging.stg_allergy (
                allergy_id, patient_id, allergy_type, category, criticality,
                allergen_system, allergen_code, allergen_display,
                reaction_code, reaction_display, severity, recorded_date,
                source_file, source_line)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.executemany(allergy_sql, allergies)

        reject_sql = """
            INSERT INTO staging.rejects (source_file, source_line, reason, raw_line)
            VALUES (%s, %s, %s, %s)
        """
        cur.executemany(reject_sql, rejects)

        conn.commit()
        logger.info("staging committed: %d patients, %d allergies, %d rejects loaded",
                    len(patients), len(allergies), len(rejects))
    except Exception:
        conn.rollback()
        logger.error("staging load FAILED, transaction rolled back", exc_info=True)
        raise
    finally:
        conn.close()

    if len(rejects) > 0 or len(warnings) > 0:
        write_alert(rejects, warnings)


if __name__ == "__main__":
    main()
