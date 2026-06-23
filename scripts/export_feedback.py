#!/usr/bin/env python3
import argparse
import datetime
import json
import sys
from pathlib import Path

def export_feedback(write: bool, dashboard_path: str):
    history_dir = Path("history")
    if not history_dir.exists():
        print("No evaluation history found. Run evaluate first.")
        sys.exit(1)

    run_files = sorted(history_dir.glob("run_*.json"), key=lambda f: f.name)
    if not run_files:
        print("No evaluation history runs found. Run evaluate first.")
        sys.exit(1)

    latest_file = run_files[-1]
    print(f"Reading latest evaluation run: {latest_file.name}")
    run_data = json.loads(latest_file.read_text())
    
    scores = run_data.get("scores", {})
    feedback_items = []
    
    # Map cases to mock accounts for demonstration: nda -> acct-001, saas -> acct-002
    account_map = {
        "nda": "acct-001",
        "saas": "acct-002"
    }

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    counter = 1

    for case_name, score_data in scores.items():
        hallucinations = score_data.get("hallucination_count", 0)
        grounding = score_data.get("citation_grounding", 1.0)
        
        # If there are hallucinations or poor grounding rate, generate a feedback log
        if hallucinations > 0 or grounding < 0.90:
            acct_id = account_map.get(case_name, "acct-001")
            
            text = (
                f"The contract review model draft for the {case_name.upper()} review generated "
                f"{hallucinations} ungrounded citation(s) and had a citation grounding rate of "
                f"{grounding:.0%}. Manual verification effort was significant."
            )
            
            feedback_item = {
                "id": f"fb-gen-{timestamp}-{counter}",
                "accountId": acct_id,
                "sourcePersona": "Associate",
                "text": text,
                "theme": "Citation Grounding & Hallucination Gate",
                "productArea": "review",
                "severity": "high" if hallucinations > 0 else "medium",
                "status": "new"
            }
            feedback_items.append(feedback_item)
            counter += 1

    if not feedback_items:
        print("No quality regressions or hallucinations found in the latest evaluation run. No feedback to generate.")
        return

    print(f"Generated {len(feedback_items)} feedback item(s) from eval failures:")
    print(json.dumps(feedback_items, indent=2))

    if write:
        feedback_file = Path(dashboard_path) / "data" / "feedback.json"
        if not feedback_file.exists():
            print(f"Error: Dashboard feedback file not found at {feedback_file.resolve()}")
            sys.exit(1)
            
        try:
            current_feedback = json.loads(feedback_file.read_text(encoding="utf-8"))
            current_feedback.extend(feedback_items)
            feedback_file.write_text(json.dumps(current_feedback, indent=2), encoding="utf-8")
            print(f"\nSuccessfully wrote feedback items to {feedback_file.resolve()}")
        except Exception as e:
            print(f"Error writing to dashboard feedback file: {e}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Export quality regressions as dashboard feedback items")
    parser.add_argument("--write", action="store_true", help="Write directly to the dashboard feedback data file")
    parser.add_argument("--dashboard", default="../legal-ai-adoption-dashboard", help="Path to dashboard root directory")
    args = parser.parse_args()
    
    export_feedback(args.write, args.dashboard)

if __name__ == "__main__":
    main()
