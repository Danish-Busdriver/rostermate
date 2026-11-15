<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

const MAX_REPORT_CHARS = 200000;
const MAX_PER_INSTALLATION_PER_DAY = 5;
const MAX_TOTAL_PER_DAY = 100;
const MAX_PER_IP_PER_DAY = 5;
const MAX_ANONYMOUS_PER_DAY = 30;
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

// Ingest-nøglen ligger i installerne og er derfor ikke en hemmelighed: begræns pr. IP (kun som hash),
// pr. installation og i en separat pulje for rapporter uden installations-ID.
function rate_limit_ip_key(string $ip): string {
    if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) return $ip;
    $packed = (string)inet_pton($ip);
    if (substr($packed, 0, 12) === str_repeat("\0", 10) . "\xff\xff") return (string)inet_ntop(substr($packed, 12)); // ::ffff:IPv4
    if (strncmp(bin2hex($packed), '2', 1) === 0 || strncmp(bin2hex($packed), '3', 1) === 0) {
        return bin2hex(substr($packed, 0, 8)) . '::/64'; // global unicast: én bruger har typisk hele /64-blokken
    }
    return $ip;
}
$ip = rate_limit_ip_key((string)($_SERVER['REMOTE_ADDR'] ?? ''));
$ipHash = hash_hmac('sha256', $ip, (string)$config['installation_hash_secret']);
function count_since(PDO $pdo, string $where, array $params): int {
    $statement = $pdo->prepare('SELECT COUNT(*) FROM rostermate_error_reports WHERE created_at >= ?' . $where);
    $statement->execute($params);
    return (int)$statement->fetchColumn();
}
if (count_since($pdo, '', [$dayAgo]) >= MAX_TOTAL_PER_DAY) fail_request(429, 'Too many reports');
if (count_since($pdo, ' AND ip_hash = ?', [$dayAgo, $ipHash]) >= MAX_PER_IP_PER_DAY) fail_request(429, 'Too many reports');
if ($hash === null) {
    if (count_since($pdo, ' AND installation_hash IS NULL', [$dayAgo]) >= MAX_ANONYMOUS_PER_DAY) fail_request(429, 'Too many reports');
} elseif (count_since($pdo, ' AND installation_hash = ?', [$dayAgo, $hash]) >= MAX_PER_INSTALLATION_PER_DAY) {
    fail_request(429, 'Too many reports');
}

$insert = $pdo->prepare(
    'INSERT INTO rostermate_error_reports (created_at, installation_hash, ip_hash, platform, app_version, report) VALUES (?, ?, ?, ?, ?, ?)'
);
$insert->execute([$now, $hash, $ipHash, $platform, $version, $report]);
$newId = (int)$pdo->lastInsertId();
$pdo->prepare('DELETE FROM rostermate_error_reports WHERE created_at < ?')
    ->execute([gmdate('Y-m-d H:i:s', time() - RETENTION_DAYS * 86400)]);
echo json_encode(['status' => 'ok', 'id' => $newId]);
