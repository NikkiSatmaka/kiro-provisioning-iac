# Kiro Access Credentials  (TEMPLATE — shape only, no real data)

> SENSITIVE — contains sign-in details. Do not commit. Distribute securely, then delete.
> This template shows the shape produced by
> `scripts/provision_passwords_and_output.py`. The generated file is
> `output/credentials.md`, which is git-ignored.

- **Generated (UTC):** YYYY-MM-DD HH:MM:SSZ
- **Sign-in URL:** https://d-xxxxxxxxxx.awsapps.com/start
- **Region code:** `ap-southeast-1`
- **Identity store:** `d-xxxxxxxxxx`
- **Kiro tier:** PRO
- **Users:** N  |  **Groups:** M

## How to sign in

1. Open Kiro. Choose sign in with your organization.
2. Choose **Sign in via IAM Identity Center**.
3. Enter the sign-in URL above and the region code.
4. Sign in with the username + password below. You will be asked to set a new password on first login.

## Users

| # | Username | Email | Group(s) | Password / OTP | Status |
|---|----------|-------|----------|----------------|--------|
| 1 | `kiro-user-01` | alice@corp.com | kiro-team-01 | `TempPass-....` | OTP set |
| 2 | `kiro-user-02` | — | kiro-team-01 | TODO — generate one-time password in console | pending password |

## Reminder on passwords

AWS IAM Identity Center does not allow an admin-chosen shared password. Each
password above is a per-user one-time password generated in the console; users
must set their own password on first sign-in.
