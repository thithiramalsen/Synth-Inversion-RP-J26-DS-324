<#
Dry-run by default. -Apply groups only the exact C2 folders in output_layout.json.
No files are deleted or rewritten. Old paths become directory junctions. All file
bytes are hashed before/after each move. Running this again is safe and verifies
existing links. Frozen production folders and real study runtimes are not targets.
#>
[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$processed = [IO.Path]::GetFullPath((Join-Path $repository 'data/processed/c2_v4'))
$plan = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'output_layout.json') | ConvertFrom-Json
$reportDirectory = Join-Path $processed 'organization_v1'

function Checked-Path([string]$relative, [bool]$destination) {
    if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains('..')) {
        throw "Only explicit repository-relative paths are allowed: $relative"
    }
    $absolute = [IO.Path]::GetFullPath((Join-Path $repository $relative))
    $insideC2 = $absolute.StartsWith($processed + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    $namedFixture = $absolute -eq [IO.Path]::GetFullPath((Join-Path $repository 'data/processed/c2-human-tests-5gudpz61'))
    if (-not $insideC2 -and -not ($namedFixture -and -not $destination)) {
        throw "Target is outside the explicitly allowed C2 scope: $absolute"
    }
    $ancestor = [IO.Path]::GetDirectoryName($absolute)
    while ($ancestor -and $ancestor.StartsWith($repository, [StringComparison]::OrdinalIgnoreCase)) {
        $ancestorItem = Get-Item -LiteralPath $ancestor -Force -ErrorAction SilentlyContinue
        if ($ancestorItem -and ($ancestorItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "An ancestor is a link; refusing an unresolved move target: $ancestor"
        }
        if ($ancestor -eq $repository) { break }
        $ancestor = [IO.Path]::GetDirectoryName($ancestor)
    }
    return $absolute
}

function File-Inventory([string]$directory) {
    $items = @(Get-ChildItem -LiteralPath $directory -Force -Recurse)
    if ($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
        throw "Nested links are not allowed in a folder being archived: $directory"
    }
    $result = [ordered]@{}
    foreach ($item in ($items | Where-Object { -not $_.PSIsContainer } | Sort-Object FullName)) {
        $relative = [IO.Path]::GetRelativePath($directory, $item.FullName).Replace('\', '/')
        $result[$relative] = [ordered]@{ bytes = $item.Length; sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    return $result
}

$resolved = foreach ($move in $plan.moves) {
    $source = Checked-Path $move.source $false
    $destination = Checked-Path $move.destination $true
    if ($source -eq $destination -or $destination.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Invalid self/nested move: $source"
    }
    $sourceItem = Get-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue
    $destinationItem = Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
    $state = 'missing_on_this_checkout'
    if ($sourceItem -and ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        if ($sourceItem.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath([string]$sourceItem.Target) -ne $destination -or -not $destinationItem) {
            throw "Existing link does not match the organization plan: $source"
        }
        $state = 'already_organized'
    } elseif ($sourceItem) {
        if (-not $sourceItem.PSIsContainer -or $destinationItem) {
            throw "Refusing to overwrite or merge directories: $source -> $destination"
        }
        $state = 'ready_to_move'
    } elseif ($destinationItem) {
        throw "Destination exists without its expected compatibility path: $destination"
    }
    [pscustomobject]@{ source = $source; destination = $destination; state = $state }
}

if (-not $Apply) {
    foreach ($entry in $resolved) {
        Write-Output ($entry.state + ': ' + [IO.Path]::GetRelativePath($repository, $entry.source) + ' -> ' + [IO.Path]::GetRelativePath($repository, $entry.destination))
    }
    Write-Output 'Dry run only. Pass -Apply to perform these checked C2-only moves.'
    return
}

# Persist before inventories outside every moving directory. This also makes an
# interrupted run auditable; no whole-repository or recursive deletion is used.
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$records = @()
foreach ($entry in $resolved) {
    if ($entry.state -eq 'missing_on_this_checkout') { continue }
    if ($entry.state -eq 'already_organized') {
        Write-Output "Verified existing junction: $($entry.source)"
        continue
    }
    Write-Output "Hashing before move: $($entry.source)"
    $before = File-Inventory $entry.source
    $identifier = [IO.Path]::GetFileName($entry.source)
    $before | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportDirectory ($identifier + '.before.json')) -Encoding utf8
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($entry.destination)) -Force | Out-Null
    Move-Item -LiteralPath $entry.source -Destination $entry.destination
    try {
        New-Item -ItemType Junction -Path $entry.source -Target $entry.destination | Out-Null
    } catch {
        if (-not (Test-Path -LiteralPath $entry.source)) {
            Move-Item -LiteralPath $entry.destination -Destination $entry.source
        }
        throw
    }
    $after = File-Inventory $entry.destination
    if (($before | ConvertTo-Json -Depth 6 -Compress) -cne ($after | ConvertTo-Json -Depth 6 -Compress)) {
        throw "Byte preservation check failed. Both locations have been retained for inspection: $($entry.source)"
    }
    $link = Get-Item -LiteralPath $entry.source -Force
    if ($link.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath([string]$link.Target) -ne $entry.destination) {
        throw "Compatibility junction verification failed: $($entry.source)"
    }
    $record = [ordered]@{ source = $entry.source; destination = $entry.destination; files = $before.Count; bytes_unchanged = $true; legacy_path_preserved = $true }
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDirectory ($identifier + '.move.json')) -Encoding utf8
    $records += $record
    Write-Output "Moved and verified $($before.Count) files: $($entry.destination)"
}
if ($records.Count) {
    [ordered]@{ schema_version = 1; scope = 'C2 only'; no_files_deleted = $true; moves = $records } |
        ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reportDirectory 'moves.json') -Encoding utf8
}
Write-Output 'Completed. Production paths and study runtimes were not moved; old paths remain usable.'
