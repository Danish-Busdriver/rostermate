<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') fail_request(405, 'Method not allowed');
if (!hash_equals('Bearer ' . (string)$config['admin_key'], supplied_header('Authorization'))) fail_request(401, 'Unauthorized');
ensure_report_table($pdo);

if (isset($_GET['id'])) {
    $statement = $pdo->prepare(
        'SELECT id, created_at, installation_hash, platform, app_version, report FROM rostermate_error_reports WHERE id = ?'
    );
    $statement->execute([(int)$_GET['id']]);
    $row = $statement->fetch();
    if (!$row) fail_request(404, 'Not found');
    $row['id'] = (int)$row['id'];
    $row['installation'] = $row['installation_hash'] ? substr((string)$row['installation_hash'], 0, 8) : '';
    unset($row['installation_hash']);
    echo json_encode(['report' => $row]);
    exit;
}

$rows = $pdo->query(
    'SELECT id, created_at, installation_hash, platform, app_version, report FROM rostermate_error_reports ORDER BY id DESC LIMIT 100'
)->fetchAll();
$reports = [];
foreach ($rows as $row) {
    $text = (string)$row['report'];
    preg_match('/\n(\d{4}-\d\d-\d\dT[^\n]{0,220})/', $text, $firstLog);
    $reports[] = [
        'id' => (int)$row['id'],
        'created_at' => $row['created_at'],
        'platform' => $row['platform'],
        'app_version' => $row['app_version'],
        'installation' => $row['installation_hash'] ? substr((string)$row['installation_hash'], 0, 8) : '',
        'has_comment' => str_contains($text, "\nBrugerens beskrivelse:\n"),
        'summary' => $firstLog[1] ?? 'Ingen loglinjer',
    ];
}
echo json_encode(['reports' => $reports]);
