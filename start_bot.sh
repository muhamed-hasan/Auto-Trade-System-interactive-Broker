#!/bin/bash
echo "Starting NextGen AutoTrade Bot..."

while true; do
    echo "[$(date)] Launching main.py..."
    ./venv/bin/python main.py
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] Bot exited normally. Stopping."
        break
    else
        echo "[$(date)] Bot crashed or gracefully rebooted on connection failure (Exit Code: $EXIT_CODE)."
        echo "Restarting in 10 seconds..."
        sleep 10
    fi
done
