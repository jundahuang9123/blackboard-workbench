"""Normalize SAST exports without rewriting their machine output."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def normalize(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("attributes"), dict) or not raw["attributes"]:
        raise ValueError("Choose a SAST *_mapping_results.json file with a nonempty attributes object.")
    if len(raw["attributes"]) > 10000:
        raise ValueError("This run exceeds the 10,000-attribute import limit.")
    items = []
    for name, value in raw["attributes"].items():
        if not isinstance(value, dict) or not isinstance(value.get("state"), dict):
            raise ValueError(f"Attribute {name} has no state object.")
        state = value["state"]
        candidates = state.get("validated_candidates") or []
        if not isinstance(candidates, list):
            raise ValueError(f"Attribute {name} has invalid candidates.")
        normalized = []
        seen = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("candidate"), str):
                raise ValueError(f"Attribute {name} contains an invalid candidate.")
            cid = digest(candidate["candidate"])[:20]
            if cid not in seen:
                normalized.append({"id": cid, "label": candidate["candidate"], "record": candidate})
                seen.add(cid)
        final = state.get("final_mapping")
        if final is not None and not isinstance(final, dict):
            raise ValueError(f"Attribute {name} has an invalid final mapping.")
        items.append({"id": digest(name)[:20], "name": name, "candidates": normalized,
                      "machine_mapping": final, "matrix": state.get("matrix") or [],
                      "original": value})
    return items


def demo():
    def candidate(label, doc, value, proximity):
        return {"candidate": label, "documentation_vote": {"accepted": doc, "reason": "Illustrative documentation assessment."},
                "example_value_vote": {"accepted": value, "reason": "Illustrative value assessment."},
                "attribute_name_mapping_proximity_vote": {"proximity": proximity, "reason": "Illustrative name assessment."},
                "historical_vote": {"accepted": True, "reason": "Illustrative precedent; not a real retrieval."}}
    a = candidate('ex:Location ex:latitude "lat" .', True, True, "high")
    b = candidate('ex:Place ex:identifier "lat" .', False, True, "low")
    c = candidate('ex:Location ex:longitude "lon" .', True, True, "high")
    return {"workbench_demo": True, "attributes": {
        "lat": {"state": {"validated_candidates": [a, b], "final_mapping": {"candidate": a["candidate"], "selection_reason": "Documentation and the paired longitude field support latitude."},
                           "matrix": [{"candidate": a["candidate"], "agents": {"documentation": a["documentation_vote"], "example_value": a["example_value_vote"]}}]}, "logs": {}},
        "lon": {"state": {"validated_candidates": [c], "final_mapping": {"candidate": c["candidate"], "selection_reason": "Illustrative selection."}}, "logs": {}}},
        "discussions": {"discussion_1": {"participants": [{"attribute": "lat", "role": "weak"}, {"attribute": "lon", "role": "strong"}], "reason": "Check the coordinate pairing.", "conclusion": "Acceptance",
        "turn_logs": [{"turn": 1, "log": [{"attribute": "lat", "response": "The example documentation describes latitude in degrees.", "commands": []}]}]}},
        "evaluation": {}, "reasoning_effect": [], "workbench_context": {"documentation": "Synthetic example: lat is latitude, lon is longitude, both in decimal degrees.", "data": {"lat": 51.26, "lon": 7.15}}}
