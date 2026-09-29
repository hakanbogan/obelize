"""The allowed `credentials=`, and a module-level client with no `api_key=` at all.

`Client.credentials` is typed for a credentials object, so the value carries
over untouched. ADR-013 D5's exemption is about a non-empty `api_key=` string
literal and this call has no `api_key=`, so the warning fires.
"""

import google.generativeai as genai
from google.oauth2 import service_account

CREDENTIALS = service_account.Credentials.from_service_account_file("service-account.json")

genai.configure(credentials=CREDENTIALS)
