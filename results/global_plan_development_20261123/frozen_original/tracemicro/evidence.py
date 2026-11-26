import hashlib
import json
from pathlib import Path

from baseline import analyze
from dependency_baseline import load_graph


class EvidenceStore:
    """Read fixed source bytes and saved official dependencies; no new extraction."""
    def __init__(self, workspace, repository, graph_json, expected_snapshot=None, expected_graph_hash=None):
        self.workspace = Path(workspace).resolve()
        self.repository = self._inside(repository)
        self.graph_path = self._inside(graph_json)
        package = analyze(self.repository)
        self.snapshot = package['snapshot']
        if expected_snapshot and self.snapshot['eligible_java_files_sha256'] != expected_snapshot:
            raise ValueError('Source snapshot does not match saved dependency input')
        raw = self.graph_path.read_bytes()
        self.graph_sha256 = hashlib.sha256(raw).hexdigest()
        if expected_graph_hash and self.graph_sha256 != expected_graph_hash:
            raise ValueError('Dependency JSON hash mismatch')
        nodes, self.edges = load_graph(json.loads(raw))
        self.files = {}
        for package_name, paths in package['candidate_services'].items():
            for path in paths:
                symbol = package_name+'.'+Path(path).stem
                if symbol in self.files:
                    raise ValueError('Ambiguous filename-based class identity')
                full_path = self._inside(self.repository/path)
                self.files[symbol] = {'path':full_path.relative_to(self.workspace).as_posix(),
                                      'sha256':hashlib.sha256(full_path.read_bytes()).hexdigest(),
                                      'lines':full_path.read_text(encoding='utf-8-sig').splitlines()}
        if set(nodes) != set(self.files):
            raise ValueError('Source filename identifiers and analyzer nodes differ')

    def _inside(self, path):
        path = Path(path)
        resolved = (self.workspace/path).resolve() if not path.is_absolute() else path.resolve()
        resolved.relative_to(self.workspace)
        return resolved

    @property
    def classes(self):
        return sorted(self.files)

    def inspect_source(self, class_name, start_line=1, end_line=None):
        info = self.files[class_name]
        if type(start_line) is not int:
            raise ValueError('start_line must be an integer')
        end_line = min(start_line+79, len(info['lines'])) if end_line is None else end_line
        if type(start_line) is not int or type(end_line) is not int or not 1 <= start_line <= end_line <= len(info['lines']) or end_line-start_line+1 > 120:
            raise ValueError('Source excerpt must be a valid 1-based range of at most 120 lines')
        return {'tool':'inspect_source','class':class_name,'path':info['path'],
                'sha256':info['sha256'],'start_line':start_line,'end_line':end_line,
                'lines':[{'line':i,'text':info['lines'][i-1]} for i in range(start_line,end_line+1)]}

    def inspect_dependencies(self, class_name):
        if class_name not in self.files:
            raise KeyError(class_name)
        return {'tool':'inspect_dependencies','class':class_name,
                'path':self.graph_path.relative_to(self.workspace).as_posix(),
                'sha256':self.graph_sha256,
                'json_pointer':'/classes/'+class_name+'/relationships',
                'outgoing':[e for e in self.edges if e['source']==class_name],
                'incoming':[e for e in self.edges if e['target']==class_name],
                'source_edge_line_references':None,
                'limitation':'Official export has no source line per edge; incoming edges derive from other classes, not this JSON pointer. Parse/resolution diagnostics incomplete.'}
