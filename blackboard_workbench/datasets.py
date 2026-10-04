"""Prepare immutable custom inputs; reference answers stay separate from model context."""
import base64
import binascii
import csv
from datetime import date, datetime, time
import hashlib
import io
import json
import math
from pathlib import Path
import re
import uuid
import zipfile

MAX_FILE = 5_000_000
MAX_ROWS = 20_000
MAX_COLUMNS = 200


def decode_file(value, suffixes):
    if not isinstance(value, dict) or not isinstance(value.get('name'), str):
        raise ValueError('Choose an input file.')
    name = Path(value['name']).name
    if Path(name).suffix.lower() not in suffixes:
        raise ValueError(f'{name}: supported formats are {", ".join(suffixes)}.')
    content = value.get('content')
    if not isinstance(content, str) or len(content) > MAX_FILE * 4 // 3 + 8:
        raise ValueError(f'{name}: file must be at most 5 MB.')
    try:
        data = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError(f'{name}: invalid file encoding.') from None
    if not data or len(data) > MAX_FILE:
        raise ValueError(f'{name}: choose a nonempty file of at most 5 MB.')
    return name, data


def text_file(data, name):
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError(f'{name}: save the file using UTF-8 encoding.') from None


def cell_value(value, csv_input=False):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if csv_input and isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.lower() in {'true', 'false'}:
            return stripped.lower() == 'true'
        # Preserve codes such as 0010 and 10-digit phone numbers as text.
        if re.fullmatch(r'-?(?:0|[1-9]\d{0,8})', stripped):
            return int(stripped)
        if re.fullmatch(r'-?(?:0|[1-9]\d*)\.\d+(?:[eE][+-]?\d+)?', stripped):
            value = float(stripped)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('The table contains a non-finite number.')
    return value


def read_table(file, sheet=None, sample_rows=20):
    if isinstance(sample_rows, bool) or not isinstance(sample_rows, int) or not 1 <= sample_rows <= 100:
        raise ValueError('Choose between 1 and 100 example rows.')
    name, data = decode_file(file, {'.csv', '.xlsx'})
    workbook = None
    sheets = []
    try:
        if name.lower().endswith('.csv'):
            text = text_file(data, name)
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
            except csv.Error:
                dialect = csv.excel
            rows = csv.reader(io.StringIO(text), dialect, strict=True)
            selected = None
        else:
            from openpyxl import load_workbook
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 40_000_000:
                    raise ValueError('The workbook exceeds the 40 MB expanded-size limit.')
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
            sheets = workbook.sheetnames
            selected = sheet or (sheets[0] if sheets else None)
            if selected not in sheets:
                raise ValueError('Choose a worksheet from this workbook.')
            rows = workbook[selected].iter_rows()
        header = next(rows, None)
        if header is None:
            raise ValueError('The table is empty.')
        headers = [str(c.value if workbook else c).strip() if (c.value if workbook else c) is not None else '' for c in header]
        while headers and not headers[-1]:
            headers.pop()
        if not headers or len(headers) > MAX_COLUMNS or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError('Use 1–200 unique, nonempty column names in the first row.')
        if any(len(h) > 200 or any(c in h for c in '\\"\n\r\t') for h in headers):
            raise ValueError('Column names must be at most 200 characters and cannot contain quotes, backslashes or control characters.')
        records, count = [], 0
        for row_index, row in enumerate(rows, 1):
            if row_index > MAX_ROWS:
                raise ValueError("Choose a table with at most 20,000 rows below the header.")
            if workbook:
                if any(c.data_type == 'f' for c in row):
                    raise ValueError('Formula cells are not supported. Export calculated values to CSV or paste values into a new workbook.')
                values = [c.value for c in row]
            else:
                values = list(row)
            if not any(v is not None and v != '' for v in values):
                continue
            if len(values) > len(headers) and any(v is not None and v != '' for v in values[len(headers):]):
                raise ValueError('A row contains values beyond the named columns.')
            count += 1
            if count > MAX_ROWS:
                raise ValueError('Choose a table with at most 20,000 nonempty rows.')
            if len(records) < sample_rows:
                values += [None] * (len(headers) - len(values))
                records.append({h: cell_value(values[i], csv_input=not workbook) for i, h in enumerate(headers)})
        if not records:
            raise ValueError('The table needs at least one data row below the header.')
        return {'table_name': name, 'sheet': selected, 'sheets': sheets, 'columns': headers,
                'row_count': count, 'sample_rows': len(records), 'data': records,
                'table_sha256': hashlib.sha256(data).hexdigest()}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('The table could not be read. Choose a valid CSV or XLSX file.') from exc
    finally:
        if workbook:
            workbook.close()


def parse_ontologies(files):
    from rdflib import Graph
    from rdflib.namespace import RDF, RDFS, OWL
    if not isinstance(files, list) or not 1 <= len(files) <= 5:
        raise ValueError('Choose between one and five Turtle (.ttl) ontologies.')
    merged, namespaces, sources = Graph(), {}, []
    for file in files:
        name, data = decode_file(file, {'.ttl'})
        text = text_file(data, name)
        # Graph.parse follows owl:imports only when explicitly requested; here it parses local bytes only.
        graph = Graph()
        try:
            graph.parse(data=text, format='turtle')
        except Exception:
            raise ValueError(f'{name}: invalid Turtle ontology.') from None
        for prefix, uri in graph.namespaces():
            prefix = prefix or ''
            if prefix in namespaces and namespaces[prefix] != str(uri):
                raise ValueError(f'Ontology prefix "{prefix}" identifies different namespaces. Use distinct prefixes before uploading.')
            namespaces[prefix] = str(uri)
            merged.bind(prefix, uri)
        merged += graph
        sources.append({'name': name, 'sha256': hashlib.sha256(data).hexdigest(), 'triples': len(graph)})
    if not any(merged.subjects(RDF.type, OWL.Class)) and not any(merged.subjects(RDF.type, RDFS.Class)):
        raise ValueError('The ontology needs at least one owl:Class or rdfs:Class.')
    if not any(merged.subjects(RDF.type, OWL.DatatypeProperty)):
        raise ValueError('The ontology needs at least one owl:DatatypeProperty for column values.')
    return merged, sources


def reference_mapping(file, graph, columns):
    from rdflib import Graph, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL
    if file is None:
        return None
    name, data = decode_file(file, {'.json'})
    try:
        value = json.loads(text_file(data, name), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ValueError:
        raise ValueError('Reference mappings must be valid JSON.') from None
    if not isinstance(value, dict):
        raise ValueError('Reference mappings must be a JSON object keyed by column name.')
    native = 'mappings' in value and isinstance(value.get('mappings'), dict) and isinstance(value.get('prefix'), str)
    mappings = value['mappings'] if native else value
    if not mappings or any(k not in columns for k in mappings):
        raise ValueError('Reference mappings must include at least one column and may only name columns present in the table.')
    prefixes = ''.join(f'@prefix {p}: <{u}> .\n' for p, u in graph.namespaces())
    def term(v):
        if not isinstance(v, str) or any(c.isspace() for c in v):
            raise ValueError('Use a full IRI or declared ontology prefix for reference classes and properties.')
        return f'<{v}>' if v.startswith(('http://', 'https://', 'urn:')) else v
    result = {}
    for column, item in mappings.items():
        if not isinstance(item, dict):
            raise ValueError(f'{column}: reference must specify class and property.')
        try:
            g = Graph()
            if native:
                mapping = item.get('mapping')
                if not isinstance(mapping, str):
                    raise ValueError()
                g.parse(data=value['prefix'] + '\n' + mapping, format='turtle')
            else:
                g.parse(data=prefixes + f'\n{term(item.get("class"))} {term(item.get("property"))} {Literal(column).n3()} .', format='turtle')
            triples = list(g)
            if len(triples) != 1:
                raise ValueError()
            subject, predicate, obj = triples[0]
            if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef) or not isinstance(obj, Literal) or str(obj) != column:
                raise ValueError()
            if (subject, RDF.type, OWL.Class) not in graph and (subject, RDF.type, RDFS.Class) not in graph:
                raise ValueError()
            if (predicate, RDF.type, OWL.DatatypeProperty) not in graph:
                raise ValueError()
        except Exception:
            raise ValueError(f'{column}: reference must identify an ontology class and datatype property, using a declared prefix or full IRI.') from None
        result[column] = {'class': str(subject), 'property': str(predicate)}
    return result


class Datasets:
    def __init__(self, directory):
        self.directory = Path(directory) / 'datasets'

    def inspect(self, payload):
        table = read_table(payload.get('table'), payload.get('sheet'), payload.get('sample_rows', 20))
        return {**table, 'data': table['data'][:5]}

    def create(self, payload):
        table = read_table(payload.get('table'), payload.get('sheet'), payload.get('sample_rows', 20))
        graph, sources = parse_ontologies(payload.get('ontologies'))
        reference = reference_mapping(payload.get('reference'), graph, table['columns'])
        title = payload.get('title') or Path(table['table_name']).stem
        documentation = payload.get('documentation', '')
        if not isinstance(title, str) or not title.strip() or len(title) > 150:
            raise ValueError('Use a dataset name of at most 150 characters.')
        if not isinstance(documentation, str) or len(documentation) > 30000:
            raise ValueError('Documentation must be at most 30,000 characters.')
        ident = uuid.uuid4().hex
        folder = self.directory / ident
        reference_sha = hashlib.sha256(decode_file(payload['reference'], {'.json'})[1]).hexdigest() if reference is not None else None
        summary = {'reference_sha256': reference_sha, 'documentation_sha256': hashlib.sha256(documentation.encode()).hexdigest(), 'id': ident, 'title': title.strip(), **{k:v for k,v in table.items() if k not in {'data','sheets'}},
                   'ontologies': sources, 'benchmark_available': reference is not None,
                   'reference_columns': list(reference) if reference else []}
        # Persist only after all inputs validate. Generated directories never use uploaded filenames.
        folder.mkdir(parents=True)
        try:
            (folder/'ontology.ttl').write_text(graph.serialize(format='turtle'), encoding='utf-8')
            (folder/'data.json').write_text(json.dumps(table['data'], ensure_ascii=False, allow_nan=False), encoding='utf-8')
            (folder/'documentation.txt').write_text(documentation, encoding='utf-8')
            if reference is not None:
                (folder/'reference.json').write_text(json.dumps(reference), encoding='utf-8')
            (folder/'metadata.json').write_text(json.dumps(summary, ensure_ascii=False), encoding='utf-8')
        except Exception:
            import shutil
            shutil.rmtree(folder)
            raise
        return summary

    def get(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise ValueError('Choose a saved custom dataset.')
        folder = self.directory / ident
        if not (folder/'metadata.json').is_file():
            raise ValueError('Custom dataset not found. Upload and validate it first.')
        return folder, json.loads((folder/'metadata.json').read_text())

    def list(self):
        return [json.loads(p.read_text()) for p in sorted(self.directory.glob('*/metadata.json'))]
