<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

const MAX_REPORT_CHARS = 200000;
const MAX_PER_INSTALLATION_PER_DAY = 5;
const MAX_TOTAL_PER_DAY = 100;
const RETENTION_DAYS = 180;

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') fail_request(405, 'Method not allowed');
if (!hash_equals((string)$config['ingest_key'], supplied_header('X-RosterMate-Key'))) fail_request(401, 'Unauthorized');
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 1048576) fail_request(413, 'Payload too large');
$body = json_decode((string)file_get_contents('php://input'), true);
if (!is_array($body)) fail_request(400, 'Invalid JSON');
$id = strtolower(trim((string)($body['installation_id'] ?? '')));
$version = trim((string)($body['version'] ?? ''));
$platform = trim((string)($body['platform'] ?? ''));
$report = (string)($body['report'] ?? '');
if ($id !== '' && !preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $id)) fail_request(400, 'Invalid installation ID');
if (!preg_match('/^[0-9A-Za-z.+-]{1,32}$/', $version)) fail_request(400, 'Invalid version');
if (!in_array($platform, ['macos', 'windows', 'other'], true)) fail_request(400, 'Invalid platform');
if (trim($report) === '' || !mb_check_encoding($report, 'UTF-8')) fail_request(400, 'Invalid report');
if (mb_strlen($report) > MAX_REPORT_CHARS) fail_request(413, 'Report too large');

ensure_report_table($pdo);
$now = gmdate('Y-m-d H:i:s');
$dayAgo = gmdate('Y-m-d H:i:s', time() - 86400);
$hash = $id === '' ? null : hash_hmac('sha256', $id, (string)$config['installation_hash_secret']);

$total = $pdo->prepare('SELECT COUNT(*) FROM rostermate_error_reports WHERE created_at >= ?');
$total->execute([$dayAgo]);
if ((int)$total->fetchColumn() >= MAX_TOTAL_PER_DAY) fail_request(429, 'Too many reports');
if ($hash !== null) {
    $mine = $pdo->prepare('SELECT COUNT(*) FROM rostermate_error_reports WHERE installation_hash = ? AND created_at >= ?');
    $mine->execute([$hash, $dayAgo]);
    if ((int)$mine->fetchColumn() >= MAX_PER_INSTALLATION_PER_DAY) fail_request(429, 'Too many reports');
}

$insert = $pdo->prepare(
    'INSERT INTO rostermate_error_reports (created_at, installation_hash, platform, app_version, report) VALUES (?, ?, ?, ?, ?)'
);
$insert->execute([$now, $hash, $platform, $version, $report]);
$newId = (int)$pdo->lastInsertId();
$pdo->prepare('DELETE FROM rostermate_error_reports WHERE created_at < ?')
    ->execute([gmdate('Y-m-d H:i:s', time() - RETENTION_DAYS * 86400)]);
echo json_encode(['status' => 'ok', 'id' => $newId]);
