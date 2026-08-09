<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') fail_request(405, 'Method not allowed');
if (!hash_equals((string)$config['ingest_key'], supplied_header('X-RosterMate-Key'))) fail_request(401, 'Unauthorized');
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 4096) fail_request(413, 'Payload too large');
$body = json_decode((string)file_get_contents('php://input'), true);
if (!is_array($body)) fail_request(400, 'Invalid JSON');
$id = strtolower(trim((string)($body['installation_id'] ?? '')));
$version = trim((string)($body['version'] ?? ''));
$platform = trim((string)($body['platform'] ?? ''));
if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $id)) fail_request(400, 'Invalid installation ID');
if (!preg_match('/^[0-9A-Za-z.+-]{1,32}$/', $version)) fail_request(400, 'Invalid version');
if (!in_array($platform, ['macos', 'windows', 'other'], true)) fail_request(400, 'Invalid platform');
$hash = hash_hmac('sha256', $id, (string)$config['installation_hash_secret']);
$statement = $pdo->prepare(
    'INSERT INTO rostermate_installations (installation_hash, platform, app_version, first_seen_at, last_seen_at, heartbeat_count) '
    . 'VALUES (?, ?, ?, UTC_TIMESTAMP(), UTC_TIMESTAMP(), 1) '
    . 'ON DUPLICATE KEY UPDATE platform=VALUES(platform), app_version=VALUES(app_version), '
    . 'last_seen_at=UTC_TIMESTAMP(), heartbeat_count=heartbeat_count+1'
);
$statement->execute([$hash, $platform, $version]);
$daily = $pdo->prepare(
    'INSERT INTO rostermate_heartbeat_daily (installation_hash, heartbeat_date, heartbeat_count) '
    . 'VALUES (?, UTC_DATE(), 1) ON DUPLICATE KEY UPDATE heartbeat_count=heartbeat_count+1'
);
$daily->execute([$hash]);
$pdo->exec('DELETE FROM rostermate_installations WHERE last_seen_at < UTC_TIMESTAMP() - INTERVAL 365 DAY');
$pdo->exec('DELETE FROM rostermate_heartbeat_daily WHERE heartbeat_date < UTC_DATE() - INTERVAL 365 DAY');
echo json_encode(['status' => 'ok']);
