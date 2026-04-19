import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


def sanitize_json_text(text: str) -> str:
    text = re.sub(r"\bNaN\b", "null", text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = text.strip()
    if text.endswith("]."):
        text = text[:-2] + "]"
    if text.endswith("}."):
        text = text[:-2] + "}"
    return text


def read_json_data(path: Path) -> Any:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(sanitize_json_text(raw))
        except json.JSONDecodeError:
            return []


def write_json_data(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


class ObjNode:
    def __init__(self, oID: str, file_path: str):
        self.oID = oID
        self.file_path = Path(file_path)

    def FN(self) -> str:
        return str(self.file_path)

    def load(self) -> Any:
        return read_json_data(self.file_path)

    def save(self, data: Any) -> None:
        write_json_data(self.file_path, data)


class WkNode:
    def __init__(self, o: ObjNode, working_file_path: Optional[str] = None):
        self.o = o
        if working_file_path is None:
            obj_path = Path(o.FN())
            suffix = obj_path.suffix or ".json"
            working_file_path = str(obj_path.with_name(f"{obj_path.stem}.working{suffix}"))
        self.file_path = Path(working_file_path)

    def FN(self) -> str:
        return str(self.file_path)

    def load(self) -> Any:
        if self.file_path.exists():
            return read_json_data(self.file_path)
        data = self.o.load()
        self.save(data)
        return data

    def save(self, data: Any) -> None:
        write_json_data(self.file_path, data)


class EditSession:
    def __init__(self, oDict: Optional[Dict[str, WkNode]] = None):
        self.oDict: Dict[str, WkNode] = {}
        if oDict:
            for key, wk in oDict.items():
                self.add(wk, alias=key)

    def add(self, wk: WkNode, alias: Optional[str] = None) -> WkNode:
        object_name = getattr(getattr(wk, "o", None), "oID", None) or alias or "unknown"
        self.oDict[object_name] = wk
        if alias:
            self.oDict[alias] = wk

        if object_name == "llcAssets":
            self.oDict.setdefault("llcAsset", wk)
        if object_name == "llcAsset":
            self.oDict.setdefault("llcAssets", wk)

        return wk

    def get(self, name: str) -> Optional[WkNode]:
        return self.oDict.get(name)

    def unique_views(self) -> Dict[str, WkNode]:
        result: Dict[str, WkNode] = {}
        for wk in self.oDict.values():
            object_name = getattr(getattr(wk, "o", None), "oID", None)
            if object_name and object_name not in result:
                result[object_name] = wk
        return result


    def push(self, label: str = None) -> str:
        '''
        Snapshot current working files to timestamped .bak.json files.
        Call before reset() so the previous session state can be recovered.
        Returns the timestamp label used.
        '''
        from datetime import datetime
        stamp = label or datetime.now().strftime('%Y%m%d_%H%M%S')
        for wk in self.unique_views().values():
            data = wk.load()
            bak_path = Path(wk.FN()).with_suffix(f'.{stamp}.bak.json')
            write_json_data(bak_path, data)
        return stamp

    def reset(self) -> None:
        '''
        Reset all working files from their DB object files (wk.o.load()).
        This discards any unsaved working edits and restores the last published state.
        '''
        for wk in self.unique_views().values():
            wk.save(wk.o.load())


def build_default_session(base_dir: str = ".") -> EditSession:
    base_path = Path(base_dir).resolve()
    working_dir = base_path / "working"
    working_dir.mkdir(parents=True, exist_ok=True)

    mappings = [
        ("llcAssets", "llcAssets_WBGroupLLC_b8a9be15-7305-4f85-b3e3-6461e0e89c46.json"),
        ("llcExpRev", "llcExpRev_WBGroupLLC_c7d848ab-a25b-4c8e-835f-1a224da93dcd.json"),
        # v0.2: A/P and A/R transaction ledgers
        ("llcPayables",    "llcPayables_WBGroupLLC.json"),
        ("llcReceivables", "llcReceivables_WBGroupLLC.json"),
        ("llcIncomeStmt", "llcIncomeStmt_WBGroupLLC.json"),
        ("llcBalanceSheet", "llcBalanceSheet_WBGroupLLC.json"),
    ]

    session = EditSession()
    for object_name, file_name in mappings:
        obj = ObjNode(object_name, str(base_path / file_name))
        wk = WkNode(obj, str(working_dir / file_name))
        session.add(wk)

    return session
