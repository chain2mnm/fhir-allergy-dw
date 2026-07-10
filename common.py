# common.py - reads config.ini, database connection, helper functions

import configparser
import logging
import os
from datetime import date, datetime

import psycopg2


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, "config.ini"))

DB_HOST = config.get("database", "host")
DB_PORT = config.getint("database", "port")
DB_NAME = config.get("database", "dbname")
DB_USER = config.get("database", "user")

# Password: Take it from config.ini (Can also be configured via env variable)
if "DB_PASSWORD" in os.environ:
    DB_PASSWORD = os.environ["DB_PASSWORD"]
else:
    DB_PASSWORD = config.get("database", "password")

input_folder = os.path.join(BASE_DIR, config.get("source_files", "input_folder"))
PATIENT_FILE = os.path.join(input_folder, config.get("source_files", "patient_file"))
ALLERGY_FILE = os.path.join(input_folder, config.get("source_files", "allergy_file"))

CREATE_TABLES_SQL = os.path.join(BASE_DIR, config.get("pipeline", "create_tables_sql"))
ALERT_FOLDER = os.path.join(BASE_DIR, config.get("pipeline", "alert_folder"))
LOG_FOLDER = os.path.join(BASE_DIR, "logs")


def get_logger(name):
    # One shared log file for the whole pipeline: logs/pipeline.log
    # Every run will append the logs to the file and every log line gets a timestamp 

    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER)

    logger = logging.getLogger(name)
    if len(logger.handlers) > 0:
        return logger   # already set up

    logger.setLevel(logging.INFO)
    log_format = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    # Write to the log file (append mode)
    file_handler = logging.FileHandler(os.path.join(LOG_FOLDER, "pipeline.log"))
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    # Also show them on console terminal
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    return logger

# valid category values (New ones can be added on Ad-hoc basis)
VALID_CATEGORIES = ["food", "medication", "environment", "biologic", "pet allergy"]


CATEGORY_FIXES = {
    "environmental": "environment",   
    #"drug": "medication",
}


def get_connection():
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)
    return conn


def create_tables(cursor):
    f = open(CREATE_TABLES_SQL)
    sql = f.read()
    f.close()
    cursor.execute(sql)


def check_source_files():
    if not os.path.exists(PATIENT_FILE):
        raise Exception("File not found: " + PATIENT_FILE + " (check config.ini)")
    if not os.path.exists(ALLERGY_FILE):
        raise Exception("File not found: " + ALLERGY_FILE + " (check config.ini)")


def clean_text(value):
    # trim spaces, return None if the value is missing or empty
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text


def normalize_category(value):
    # trim + lowercase, fix known bad values, check against the category list
    text = clean_text(value)
    if text is None:
        return None
    text = text.lower()
    if text in CATEGORY_FIXES:
        text = CATEGORY_FIXES[text]
    if text in VALID_CATEGORIES:
        return text
    get_logger("cleansing").warning("cannot map category: %r", value)
    return None


def parse_date(value):
    # '1971-04-05': date, None if missing or invalid
    text = clean_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[0:10])
    except ValueError:
        return None


def parse_timestamp(value):
    # '2020-01-01T09:00:00+00:00': datetime, None if missing or invalid
    text = clean_text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
