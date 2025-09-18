# planning-center-integration

## Getting Started

1. (Optional) Create and activate a virtual environment.
2. Install the required timezone data package (needed on Windows and minimal Python installs):

   ```bash
   python -m pip install tzdata
   ```

3. Set the Planning Center credentials as environment variables before running the script:

   **PowerShell (Windows)**
   ```powershell
   $env:PLANNING_CENTER_APP_ID = "<your-app-id>"; $env:PLANNING_CENTER_SECRET = "<your-secret>"; python main.py 2025-09-21
   ```

   **Command Prompt (Windows)**
   ```cmd
   cmd /c "set PLANNING_CENTER_APP_ID=<your-app-id> && set PLANNING_CENTER_SECRET=<your-secret> && python main.py 2025-09-21"
   ```

   **macOS / Linux (bash or zsh)**
   ```bash
   PLANNING_CENTER_APP_ID="<your-app-id>" PLANNING_CENTER_SECRET="<your-secret>" python main.py 2025-09-21
   ```

4. Run the script with the desired date (text output is the default; pass `--format json` for JSON):

   ```bash
   python main.py 2025-09-21
   ```

JSON output resembles:

```json
{
  "plan": [
    {
      "time": "9:00 AM",
      "items": [
        {"title": "Countdown", "sequence": 1, "length": 300}
      ]
    }
  ]
}
```

Text output resembles:

```
9:00 AM
1: Countdown - 300 seconds

```

## Project Structure

- `main.py` - Entry point that performs authenticated plan, plan-time, service time collection, plan item retrieval, and plan-time item grouping logic.


