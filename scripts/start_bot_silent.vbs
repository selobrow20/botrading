Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\bot saham"
WshShell.Run "cmd /c uv run python main.py run-all", 0, False
Set WshShell = Nothing
