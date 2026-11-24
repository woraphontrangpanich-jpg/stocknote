# Creates "Stock Note" shortcuts on the Desktop and in the Start Menu.
# Run again any time the folder is moved.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host 'Setting up for the first time...'
    py -m venv (Join-Path $root '.venv')
    & (Join-Path $root '.venv\Scripts\python.exe') -m pip install -q -r (Join-Path $root 'requirements.txt')
}
$name = 'Stock Note'
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "$name.lnk"))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '"' + (Join-Path $root 'launcher.pyw') + '"'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = (Join-Path $root 'frontend\app.ico') + ',0'
    $lnk.Description = 'Stock Note'
    $lnk.Save()
    Write-Host "Created $($lnk.FullName)"
}
