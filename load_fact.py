# Step 3 - Load FACT table - fact_allergy_event
# The joins to the dimension tables pick up the surrogate keys.ON CONFLICT on the source allergy id makes reruns safe.

from common import get_connection, get_logger

logger = get_logger("load_fact")


def load_fact(cur):
    sql = """
        INSERT INTO dw.fact_allergy_event (
            patient_key, allergen_key, reaction_key, severity_key,
            recorded_date, source_allergy_id, source_file)
        SELECT
            COALESCE(dp.patient_key, unk.patient_key),
            da.allergen_key,
            dr.reaction_key,
            ds.severity_key,
            s.recorded_date,
            s.allergy_id,
            s.source_file
        FROM staging.stg_allergy s
        LEFT JOIN dw.dim_patient dp
               ON dp.patient_id = s.patient_id
              AND dp.is_current = TRUE
        JOIN dw.dim_patient unk
               ON unk.patient_id = 'UNKNOWN'
              AND unk.is_current = TRUE
        JOIN dw.dim_allergen da
               ON  da.allergen_code = COALESCE(s.allergen_code, 'UNKNOWN')
               AND da.category      = COALESCE(s.category, 'unknown')
               AND da.allergy_type  = COALESCE(s.allergy_type, 'unknown')
        JOIN dw.dim_reaction dr
               ON dr.reaction_code = COALESCE(s.reaction_code, 'UNKNOWN')
        JOIN dw.dim_severity ds
               ON  ds.severity    = COALESCE(s.severity, 'unknown')
               AND ds.criticality = COALESCE(s.criticality, 'unknown')
        ON CONFLICT (source_allergy_id) DO UPDATE SET
            patient_key   = EXCLUDED.patient_key,
            allergen_key  = EXCLUDED.allergen_key,
            reaction_key  = EXCLUDED.reaction_key,
            severity_key  = EXCLUDED.severity_key,
            recorded_date = EXCLUDED.recorded_date,
            loaded_at     = now()
    """
    cur.execute(sql)
    return cur.rowcount


def quality_checks(cur, fact_count):
    logger.info("--- data quality report ---")

    cur.execute("SELECT COUNT(*) FROM staging.stg_allergy")
    staging_count = cur.fetchone()[0]
    logger.info("allergy rows in staging:  %d", staging_count)

    cur.execute("SELECT COUNT(*) FROM staging.rejects")
    reject_count = cur.fetchone()[0]
    logger.info("rejected rows:            %d", reject_count)

    logger.info("fact rows loaded/updated: %d", fact_count)

    # source_allergy_ids of Unknown patient (bad patient reference)
    cur.execute("""
        SELECT f.source_allergy_id
        FROM dw.fact_allergy_event f
        JOIN dw.dim_patient d ON d.patient_key = f.patient_key
        WHERE d.patient_id = 'UNKNOWN'
        ORDER BY f.source_allergy_id
    """)

    unknown_patient_ids = [row[0] for row in cur.fetchall()]
    unknown_count = len(unknown_patient_ids)
    logger.info("facts w/ unknown patient: %d", unknown_count)
    if unknown_count > 0:
        logger.warning(
            "some allergies reference patients that are not in the patient file - "
            "report to the upstream team. source_allergy_ids: %s",
            unknown_patient_ids,
        )

    # Duplicate checko n the FACT table.
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT source_allergy_id
            FROM dw.fact_allergy_event
            GROUP BY source_allergy_id
            HAVING COUNT(*) > 1
        ) duplicates
    """)

    duplicate_count = cur.fetchone()[0]
    logger.info("duplicate facts:          %d", duplicate_count)

    # Active record check.
    cur.execute("""
        SELECT COUNT(*)
        FROM dw.fact_allergy_event f
        JOIN dw.dim_patient d ON d.patient_key = f.patient_key
        WHERE d.is_current = FALSE
    """)
    
    stale_count = cur.fetchone()[0]
    logger.info("facts on old version:     %d", stale_count)

    if duplicate_count > 0 or stale_count > 0:
        raise Exception("hard data quality check failed - stopping")


def main():
    logger.info("step 3: fact load started")
    conn = get_connection()
    try:
        cur = conn.cursor()
        fact_count = load_fact(cur)
        quality_checks(cur, fact_count)
        conn.commit()
        logger.info("fact committed")
    except Exception:
        conn.rollback()
        logger.error("fact load FAILED, transaction rolled back", exc_info=True)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
