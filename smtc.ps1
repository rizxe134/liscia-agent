param([string]$Action = "list", [string]$Match = "")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); [void]$task.Wait(5000); $task.Result }
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
function Describe($s) {
  $p = $null; try { $p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties]) } catch {}
  [ordered]@{ app = $s.SourceAppUserModelId; status = $s.GetPlaybackInfo().PlaybackStatus.ToString(); title = $(if ($p) { $p.Title } else { "" }); artist = $(if ($p) { $p.Artist } else { "" }) }
}
$sessions = @($mgr.GetSessions())
$res = [ordered]@{ ok = $true; action = $Action; sessions = @($sessions | ForEach-Object { Describe $_ }) }
if ($Action -ne "list") {
  $m = $Match.ToLower()
  $s = $sessions | Where-Object { $m -and $_.SourceAppUserModelId.ToLower().Contains($m) } | Select-Object -First 1
  if (-not $s -and -not $m) { $s = $mgr.GetCurrentSession() }
  if (-not $s) { $res.ok = $false; $res.error = "no media session for '$Match'" }
  else {
    $call = switch ($Action) { "pause" { $s.TryPauseAsync() } "play" { $s.TryPlayAsync() } "toggle" { $s.TryTogglePlayPauseAsync() }
                               "next" { $s.TrySkipNextAsync() } "previous" { $s.TrySkipPreviousAsync() } "stop" { $s.TryStopAsync() } }
    $res.sent = [bool](Await $call ([bool]))
    Start-Sleep -Milliseconds 900
    $res.after = Describe $s
  }
}
$res | ConvertTo-Json -Compress -Depth 4
