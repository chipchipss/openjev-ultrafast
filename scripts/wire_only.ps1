$wire = Start-Process -FilePath "D:\openjev-models\decider\.venv\Scripts\python.exe" `
    -ArgumentList @("-m","startlux_decision.gguf_server",
                    "--model-dir","D:\openjev-models\startlux-decision-2b",
                    "--llama","http://127.0.0.1:8081",
                    "--port","8090") `
    -WindowStyle Hidden -PassThru -WorkingDirectory "D:\openjev-models\startlux-decision-2b" `
    -RedirectStandardOutput "C:\Users\Administrator\openjev-ultrafast\logs\startlux-wire.log" `
    -RedirectStandardError "C:\Users\Administrator\openjev-ultrafast\logs\startlux-wire.err.log"
Write-Host "wire pid $($wire.Id)"
