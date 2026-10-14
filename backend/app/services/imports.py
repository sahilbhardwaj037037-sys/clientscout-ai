import csv
import io
from pydantic import ValidationError
from app.schemas.lead import LeadCreate

MAX_BYTES = 1024 * 1024
MAX_ROWS = 500
ALLOWED_COLUMNS = {'website_url', 'business_name', 'category', 'location', 'status', 'notes'}


def parse_csv(data: bytes):
    if len(data) > MAX_BYTES:
        raise ValueError('CSV must be at most 1 MiB.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('CSV must be UTF-8 encoded.') from None
    if '\x00' in text:
        raise ValueError('CSV contains invalid null characters.')
    try:
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        headers = next(reader)
        headers = [header.strip().lower() for header in headers]
        if not headers or len(headers) != len(set(headers)):
            raise ValueError('CSV headers must be unique.')
        if 'website_url' not in headers:
            raise ValueError('CSV requires a website_url column.')
        unknown = set(headers) - ALLOWED_COLUMNS
        if unknown:
            raise ValueError('Unsupported CSV columns: ' + ', '.join(sorted(unknown)))
        rows = []
        for values in reader:
            if not values or all(not value.strip() for value in values):
                continue
            if len(rows) >= MAX_ROWS:
                raise ValueError('CSV must contain at most 500 non-empty data rows.')
            line = reader.line_num
            if len(values) != len(headers):
                rows.append((line, None, 'Column count does not match the header.'))
                continue
            record = dict(zip(headers, values))
            if not record.get('status', '').strip():
                record.pop('status', None)
            try:
                rows.append((line, LeadCreate.model_validate(record), None))
            except ValidationError as error:
                message = '; '.join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
                rows.append((line, None, message))
        if not rows:
            raise ValueError('CSV has no non-empty data rows.')
        return rows
    except (StopIteration, csv.Error) as error:
        raise ValueError('CSV is empty or malformed; use comma-separated UTF-8 with a header.') from error
