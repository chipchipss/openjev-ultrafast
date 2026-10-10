# 谁在吃内存：按进程名聚合工作集，前 12 名。只读，不动任何进程。
$g = Get-Process | Group-Object ProcessName
$rows = foreach ($x in $g) {
    $mb = [int](($x.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB)
    [PSCustomObject]@{ Name = $x.Name; Procs = $x.Count; WS_MB = $mb }
}
$rows | Sort-Object WS_MB -Descending | Select-Object -First 12 |
    ForEach-Object { "{0,8} MB  x{1,-3} {2}" -f $_.WS_MB, $_.Procs, $_.Name }
$os = Get-CimInstance Win32_OperatingSystem
"free MB = {0}   total MB = {1}" -f [int]($os.FreePhysicalMemory / 1024), [int]($os.TotalVisibleMemorySize / 1024)
