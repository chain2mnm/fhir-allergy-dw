# FHIR Allergy Pipeline

This is my solution for the data engineering assignment. It reads the two
FHIR NDJSON files (Patient and AllergyIntolerance), cleans & parses the data and
loads a star schema (4 dimension tables + 1 fact table) into PostgreSQL database.

## What you need:

- Python 3.10 or newer
- PostgreSQL running locally (I tested with 18.3)
- one Python package: psycopg2-binary (to establish the postgresql connection with py)

## How to run the pipeline E2E:

1. Create the database:

       createdb fhir_dw

2. Create a venv and install required packages (Please check if the solution runs without, 
      if yes then you can skip  this step):

  Set up a virtual environment (if not available), then install the required items from requirements.txt.

       python3 -m venv venv
       source venv/bin/activate        
       pip install -r requirements.txt

3. Check config.ini - DB host/port/user/password and the input folder are
   set there. By default it expects the two NDJSON files in data/input/
   (they are included). If your postgres user or password is different,
   change it in the database section. 

4. Run the pipeline:

   To run all at once:   python run_all.py

   This runs the three steps in order:
   - load_stage.py  -> parses + cleans the files, loads the staging tables
   - load_dim.py    -> loads the dimensions (dim_patient is SCD type 2, rest are SCD type 1)
   - load_fact.py   -> loads the fact table and prints data quality checks

   You can also run the three scripts one by one in that order.
   The whole thing takes a few seconds. Tables are created automatically
   on the first run.

## What to expect in the output:

- With the provided files you should see: 10 patients, 36 allergy records
  loaded into the fact table, and 2 records in staging.rejects. 
- The 2 critical issues are flagged as
  rejects which are due to broken JSON are separated from the flow.
- For non-critical issues, the data is logged in alert + log file.

## Logging:

Every run appends to logs/pipeline.log file. Each line has a timestamp, the level, and the script
that wrote it. 

## Anomalies Observed:

1. Some allergies references patients that are not present in Patient source file. Count: 1
2. Descrepency in the source data are classified into critical and non-critical issues. 
   Critical ones (Like broken  JSON, missing key attributes etc) are blocked 
   and sent to staging.rejects table (will be checked with upstream), non-critical ones will be processed with Unknown label and logged in logs and alert file (Like missing postal codes, missing recorded_dates etc).
3. reaction and severity dimensions are built, Although no data from source is observed.

## A few notes on the design:

- Each dimension has an UNKNOWN row. When a value is missing in the
  source (for example the files have no reaction/severity data at all),
  the fact row points there instead of being dropped or getting a NULL
  foreign key.
- All scripts are rerunnable. Dimensions upsert on their natural keys and
  the fact upserts on the allergy id, so running the pipeline twice gives
  the same result.
- dim_patient keeps history (SCD2). If a patient's address or phone
  changes in a later file, the old row is closed and a new current row is
  inserted. The other dimensions are plain SCD1 since they need history tracking.
- Each step runs in one transaction - if something fails, that step is
  rolled back completely.
- The source files contain some deliberately dirty data (bad categories
  like "environmental ", a recordedDate that just says
  "date", the same allergen code with two different display texts). All
  of it is handled during cleansing - details are in the code comments.
- Currently reaction and severity seem to be empty in the source file. Both dimensions
  are created. In the future if the data starts populating, the dims will start loading.

