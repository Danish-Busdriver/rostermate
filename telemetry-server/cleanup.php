<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (PHP_SAPI !== 'cli') fail_request(404, 'Not found');
$deleted = $pdo->exec('DELETE FROM rostermate_installations WHERE last_seen_at < UTC_TIMESTAMP() - INTERVAL 365 DAY');
echo json_encode(['status' => 'ok', 'deleted' => $deleted]) . PHP_EOL;
