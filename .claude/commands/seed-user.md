---
description: Create a single dummy user in the database
allowed-tools: Read, Write, Bash(venv/bin/python:*)
---

Read database/db.py to understand the users table schema and the get_db() helper.

Run the script with `venv/bin/python`, not `python3` — db.py imports werkzeug,
which only exists inside the project virtualenv.

Then write and run a Python script using Bash that:

Generates a realistic random American user using your own knowledge of common American names across regions:

Name: a realistic American first + last name
Email: derived from the name with a random 2-3 digit number suffix (e.g. michael.anderson47@gmail.com)
Password: "password123" hashed with werkzeug's generate_password_hash
created_at: current datetime
Checks if the generated email already exists in the users table. If it does, regenerate until unique.

Inserts the user into the database using the same get_db() pattern found in db.py.

Prints confirmation:

id
name
email
