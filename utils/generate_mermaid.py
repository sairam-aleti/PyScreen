import json
import os
import argparse

def generate_mermaid(json_path, output_md_path):
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return False
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to load JSON: {e}")
        return False

    workflows = data.get("core_workflows", [])
    if not workflows:
        workflows = data.get("workflows", [])

    if not workflows:
        print("No workflows found in JSON.")
        return False

    mermaid_code = ["flowchart TD"]
    
    for i, wf in enumerate(workflows):
        path = wf.get("path", "")
        if not path:
            continue
            
        # Parse State 0 -> State 10 -> State 11
        states = [s.strip() for s in path.split("->")]
        
        for j in range(len(states) - 1):
            src = states[j].replace("State ", "S")
            dst = states[j+1].replace("State ", "S")
            
            # Use workflow index as pseudo-action label to make it readable
            label = f"Flow {i+1} step {j+1}"
            mermaid_code.append(f"    {src}[{states[j]}] -- \"{label}\" --> {dst}[{states[j+1]}]")

    # Add markdown wrapper
    markdown_content = f"""# Application Workflow Map

```mermaid
{chr(10).join(mermaid_code)}
```

> **Note:** This diagram is auto-generated from the extracted core workflows.
"""

    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
        
    print(f"Saved flowchart to {output_md_path}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Mermaid flowchart from PyScreen JSON report")
    parser.add_argument("--input", required=True, help="Path to t0.0_report.json")
    parser.add_argument("--output", default="workflow_map.md", help="Path to output markdown file")
    
    args = parser.parse_args()
    generate_mermaid(args.input, args.output)
