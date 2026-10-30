import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

# Read SQL file
with open('schema.sql', 'r') as f:
    sql_content = f.read()

# Connect to MySQL
conn = pymysql.connect(
    host=os.environ.get("MYSQL_HOST", "localhost"),
    user=os.environ.get("MYSQL_USER", "root"),
    password=os.environ.get("MYSQL_PASSWORD", "root"), # 🔴 Put your real password here!
    database=os.environ.get("MYSQL_DB", "ecommerce_management"),                 # 🔴 Added this line! Put your database name here
    autocommit=True # 🔴 Forces MySQL to instantly save any website inputs automatically
)

try:
    with conn.cursor() as cursor:
        # Execute multiple statements cleanly
        for statement in sql_content.split(';'):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
    print("✓ Database initialized successfully! Website and Workbench are connected.")
except Exception as e:
    print(f"✗ Error: {e}")
finally:
    conn.close()