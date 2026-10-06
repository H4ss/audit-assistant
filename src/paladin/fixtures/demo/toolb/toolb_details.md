# ToolB scan report — ShopApp

<!-- Rapport FICTIF pour la démo Paladin. Format : profil `toolb-md-v1`. -->

- **Application**: ShopApp
- **Version**: release
- **Scan date**: 2026-09-30

## TB-0001 · SQL injection

- **Rule**: TB.SQLI.001
- **Severity**: High
- **File**: shop-api/app/orders.py
- **Line**: 12
- **CWE**: CWE-89

### Description

User-controlled `customer` parameter is concatenated into a SQL statement.

### Evidence

```python
sql = "SELECT id, total FROM orders WHERE customer = '" + customer + "'"
```

## TB-0002 · SQL injection

- **Rule**: TB.SQLI.001
- **Severity**: High
- **File**: shop-api/app/products.py
- **Line**: 11
- **CWE**: CWE-89

### Description

Query built near user input `term`.

## TB-0003 · Reflected cross-site scripting

- **Rule**: TB.XSS.004
- **Severity**: Critical
- **File**: shop-api/app/search.py
- **Line**: 7
- **CWE**: CWE-79

### Description

Search term reflected into HTML without encoding.

## TB-0004 · Reflected cross-site scripting

- **Rule**: TB.XSS.004
- **Severity**: Medium
- **File**: shop-api/app/search.py
- **Line**: 12
- **CWE**: CWE-79

### Description

String concatenation into HTML in `render_help_page`.

## TB-0005 · Log injection

- **Rule**: TB.LOG.002
- **Severity**: Medium
- **File**: shop-api/app/logging_utils.py
- **Line**: 7
- **CWE**: CWE-117

### Description

Unsanitized data written to application log via `audit()`.

## TB-0006 · Predictable random value

- **Rule**: TB.RAND.001
- **Severity**: High
- **File**: billing-lib/billing/tokens.py
- **Line**: 8
- **CWE**: CWE-338

### Description

`random.choice` used to build a payment link token.

## TB-0008 · Weak hash algorithm

- **Rule**: TB.CRYPTO.007
- **Severity**: Low
- **File**: billing-lib/billing/hashing.py
- **Line**: 7
- **CWE**: CWE-328

### Description

MD5 usage detected.

## TB-0009 · Path traversal

- **Rule**: TB.PATH.003
- **Severity**: High
- **File**: shop-api/app/files.py
- **Line**: 10
- **CWE**: CWE-22

### Description

File name from request used to build a filesystem path.

## Scan statistics

Files scanned: 11. Rules enabled: 412.
