# Step 2 - Load Dimensions:
# dim_patient:  SCD Type 2 (History stored: A change closes the old row and inserts a new current row)
# other dims:    SCD Type 1 (update in place: codes do not change meaning, so no history is needed)
 
from common import get_connection, create_tables, get_logger
 
logger = get_logger("load_dim")
 
 
def load_dim_patient(cur):

    # SCD2 step 1: close the current row of every patient that changed.
    close_sql = """
        UPDATE dw.dim_patient d
        SET effective_to = now(),
            is_current   = FALSE
        FROM staging.stg_patient s
        WHERE d.patient_id = s.patient_id
          AND d.is_current = TRUE
          AND (d.full_name    IS DISTINCT FROM s.full_name
               OR d.gender       IS DISTINCT FROM s.gender
               OR d.birth_date   IS DISTINCT FROM s.birth_date
               OR d.address_line IS DISTINCT FROM s.address_line
               OR d.city         IS DISTINCT FROM s.city
               OR d.state        IS DISTINCT FROM s.state
               OR d.postal_code  IS DISTINCT FROM s.postal_code
               OR d.country      IS DISTINCT FROM s.country
               OR d.phone        IS DISTINCT FROM s.phone)
    """
    cur.execute(close_sql)
    logger.info("dim_patient: %d old version(s) closed", cur.rowcount)
 
    # SCD2 step 2: Covers brand new patients and the ones that just changed
    insert_sql = """
        INSERT INTO dw.dim_patient (
            patient_id, full_name, gender, birth_date, address_line,
            city, state, postal_code, country, phone,
            effective_from, effective_to, is_current)
        SELECT s.patient_id, s.full_name, s.gender, s.birth_date,
               s.address_line, s.city, s.state, s.postal_code,
               s.country, s.phone,
               now(), NULL, TRUE
        FROM staging.stg_patient s
        LEFT JOIN dw.dim_patient d
               ON d.patient_id = s.patient_id
              AND d.is_current = TRUE
        WHERE d.patient_id IS NULL
    """
    cur.execute(insert_sql)
    logger.info("dim_patient: %d new version(s) inserted", cur.rowcount)
 
 
def load_dim_allergen(cur):
    # one row per (group by code, category, type)
    # 'UNKNOWN' (upper) for missing business-key codes, 'unknown' (lower) for missing descriptive attributes.
    sql = """
        INSERT INTO dw.dim_allergen (allergen_code, allergen_display,
                                     allergen_system, category, allergy_type)
        SELECT COALESCE(allergen_code, 'UNKNOWN'),
               MAX(allergen_display),
               MAX(COALESCE(allergen_system, 'unknown')),
               COALESCE(category, 'unknown'),
               COALESCE(allergy_type, 'unknown')
        FROM staging.stg_allergy
        GROUP BY COALESCE(allergen_code, 'UNKNOWN'),
                 COALESCE(category, 'unknown'),
                 COALESCE(allergy_type, 'unknown')
        ON CONFLICT (allergen_code, category, allergy_type)
        DO UPDATE SET allergen_display = EXCLUDED.allergen_display
    """
    cur.execute(sql)
    logger.info("dim_allergen: %d row(s) inserted/updated", cur.rowcount)
 
 
def load_dim_reaction(cur):
    # same UPPER/lower convention as dim_allergen
    sql = """
        INSERT INTO dw.dim_reaction (reaction_code, reaction_display)
        SELECT COALESCE(reaction_code, 'UNKNOWN'),
               MAX(reaction_display)
        FROM staging.stg_allergy
        GROUP BY COALESCE(reaction_code, 'UNKNOWN')
        ON CONFLICT (reaction_code)
        DO UPDATE SET reaction_display = EXCLUDED.reaction_display
    """
    cur.execute(sql)
    logger.info("dim_reaction: %d row(s) inserted/updated", cur.rowcount)
 
 
def load_dim_severity(cur):
    # no business-key code here, both attributes are descriptive - lowercase throughout
    sql = """
        INSERT INTO dw.dim_severity (severity, criticality)
        SELECT DISTINCT COALESCE(severity, 'unknown'),
                        COALESCE(criticality, 'unknown')
        FROM staging.stg_allergy
        ON CONFLICT (severity, criticality) DO NOTHING
    """
    cur.execute(sql)
    logger.info("dim_severity: %d row(s) inserted/updated", cur.rowcount)
 
 
def main():
    logger.info("step 2: dimension load started")
    conn = get_connection()
    try:
        cur = conn.cursor()

        create_tables(cur)
 
        load_dim_patient(cur)
        load_dim_allergen(cur)
        load_dim_reaction(cur)
        load_dim_severity(cur)
 
        conn.commit()
        logger.info("dimensions committed")
    except Exception:
        conn.rollback()
        logger.error("dimension load FAILED, transaction rolled back", exc_info=True)
        raise
    finally:
        conn.close()
 
 
if __name__ == "__main__":
    main()