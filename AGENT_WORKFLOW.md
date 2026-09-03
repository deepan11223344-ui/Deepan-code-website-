# DeepanCode Agent Task Completion Guide

## 1. General Task-Completion Pipeline

```
User Input → Intent Understanding → Plan Generation → Execution → Verification → Reporting
```

| Phase | Description |
|-------|-------------|
| **Input Reception** | Agent receives user command via terminal prompt |
| **Intent Understanding** | Agent analyzes request, identifies required tools |
| **Plan Generation** | Agent creates step-by-step execution plan |
| **Execution** | Agent calls tools (read_file, run_command, etc.) |
| **Verification** | Agent validates results against expected outcome |
| **Reporting** | Agent displays formatted output to user |

---

## 2. Step-by-Step Checklist

### Pre-Execution
```
[ ] Receive user input
[ ] Parse intent (what task? what tools needed?)
[ ] Check prerequisites (file exists? permissions OK?)
[ ] Generate execution plan
[ ] Display plan to user (if high effort mode)
```

### Execution (Visible Steps)
```
Step 1: Understanding your request...
Step 2: Planning execution steps...
Step 3: Executing: [tool_name]...
Step 4: Processing result...
Step 5: Task completed!
```

### Execution
```
[ ] Execute tool calls in sequence
[ ] Capture output from each tool
[ ] Handle errors immediately
[ ] Retry failed operations (max 3 attempts)
[ ] Log all actions for audit trail
```

### Post-Execution
```
[ ] Verify final result
[ ] Display formatted output
[ ] Update token usage stats
[ ] Save task to history (if save_task called)
[ ] Return to prompt
```

---

## 3. Example Walkthrough

**User Task:** "List files modified in the last day"

### Step 1: Agent Receives Input
```
deepancode> List files modified in the last day
```

### Step 2: Intent Understanding
```
Agent Analysis:
- Task type: File listing
- Required tool: run_command
- Platform: Windows (PowerShell)
- Command needed: Get-ChildItem with date filter
```

### Step 3: Plan Generation
```
Execution Plan:
1. Run PowerShell command to find files modified in last 24 hours
2. Format output as bullet points
3. Display results
```

### Step 4: Execution
```powershell
# Agent executes:
Get-ChildItem -Path . -Recurse | Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-1) } | Select-Object Name, LastWriteTime
```

### Step 5: Output Display
```
* main.py - Modified: 2026-07-06 14:32:15
* config.json - Modified: 2026-07-06 13:18:42
* README.md - Modified: 2026-07-06 10:05:33
```

### Step 6: Verification
```
Agent Verification:
- Files found: 3
- All modified within 24 hours: Yes
- Output format: Bullet points (*)
- Task complete: Yes
```

---

## 4. Error Handling & Retries

### Common Errors
| Error | Handling |
|-------|----------|
| File not found | Suggest similar files, ask for clarification |
| Permission denied | Notify user, suggest running as admin |
| Command timeout | Retry once, then report failure |
| Invalid input | Ask user to rephrase |

### Retry Logic
```
Attempt 1: Execute command
    ↓ Failed
Attempt 2: Execute with fallback approach
    ↓ Failed
Attempt 3: Report error to user with explanation
```

### Logging
```
All actions logged to: ~/.deepans-code/logs/
- Timestamp
- User input
- Tools called
- Results returned
- Token usage
```

---

## 5. CLI Visibility Features

### Step-by-Step Progress Display
```
deepancode> List files modified in the last day

Step 1: Understanding your request...
Step 2: Planning execution steps...
Step 3: Executing: run_command...
>> run_command({"command": "Get-ChildItem -Path . -Recurse | Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-1) }"})
┌──────────────────────────────────────────────────────────────┐
│ Output                                                       │
│ * main.py - Modified: 2026-07-06 14:32:15                   │
│ * config.json - Modified: 2026-07-06 13:18:42               │
│ * README.md - Modified: 2026-07-06 10:05:33                 │
└──────────────────────────────────────────────────────────────┘
Step 4: Processing result...
Step 5: Task completed!

* Here are the files modified in the last day:
* main.py (Modified: 2026-07-06 14:32:15)
* config.json (Modified: 2026-07-06 13:18:42)
* README.md (Modified: 2026-07-06 10:05:33)
```

### Progress Indicators
```
* Step 1/3: Reading file...
* Step 2/3: Analyzing content...
* Step 3/3: Generating output...
```

### Token Usage Display
```
Token Usage:
  Daily:   [########----------] 40.0% (400,000/1,000,000)
  Monthly: [##----------------] 2.0% (400,000/20,000,000)
  Requests: 15
```

---

## 6. Deterministic & Reproducible Design

### Principles
1. **Same input → Same output** (deterministic)
2. **All steps visible** (transparent)
3. **All actions logged** (auditable)
4. **Errors handled gracefully** (resilient)

### Audit Trail Example
```
[2026-07-06 14:32:15] USER: List files modified in the last day
[2026-07-06 14:32:15] AGENT: Intent understood - file listing task
[2026-07-06 14:32:15] AGENT: Plan generated - 1 step
[2026-07-06 14:32:15] AGENT: Executing run_command
[2026-07-06 14:32:16] TOOL: Get-ChildItem output received
[2026-07-06 14:32:16] AGENT: Verification passed
[2026-07-06 14:32:16] AGENT: Output displayed to user
[2026-07-06 14:32:16] STATS: Tokens used: 1,245
```
