'''
SMTP Setup for Hosted environment

1. Open browser incognito - to assure you are using the correct business
   BUS account (Chrome-Mac: Cmd + Shift + N)
2. Login into google acct of BUS email - wbgroupmgr@gmail.com
3. go to https://myaccount.google.com/apppasswords -- sign in again
4. Create a new App Password named PA-SMTP
5. Copy the 16 chars with no spaces
6. Update wsgi.py with SMTP_APP_PASSWORD, reload PA web app
7. Run this script from a PA Bash console on port 587

Success: LOGIN OK
'''

import smtplib

print("Get App Password from wsgi.py of web configuration file.")
pw = input("Enter App Password (16 chars, no spaces): ")
print(f"FROM:wbgroupmgr@gmail.com PASS set:{bool(pw)}")

with smtplib.SMTP('smtp.gmail.com', 587) as s:
    s.ehlo()
    s.starttls()
    s.ehlo()
    s.login('wbgroupmgr@gmail.com', pw)
    print('LOGIN OK')
