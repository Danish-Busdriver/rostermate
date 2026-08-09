<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') fail_request(405, 'Method not allowed');
$authorization = supplied_header('Authorization');
$expected = 'Bearer ' . (string)$config['admin_key'];
if (!hash_equals($expected, $authorization)) fail_request(401, 'Unauthorized');
$counts = $pdo->query(
    'SELECT COUNT(*) total, '
    . 'SUM(last_seen_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY) active_7_days, '
    . 'SUM(last_seen_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY) active_30_days, '
    . 'SUM(last_seen_at >= UTC_TIMESTAMP() - INTERVAL 90 DAY) active_90_days '
    . 'FROM rostermate_installations'
)->fetch();
$platforms = $pdo->query(
    'SELECT platform, COUNT(*) count FROM rostermate_installations '
    . 'WHERE last_seen_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY GROUP BY platform ORDER BY count DESC'
)->fetchAll();
$versions = $pdo->query(
    'SELECT app_version version, COUNT(*) count FROM rostermate_installations '
    . 'WHERE last_seen_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY GROUP BY app_version ORDER BY count DESC'
)->fetchAll();
$newInstallations = $pdo->query(
    'SELECT '
    . 'SUM(first_seen_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY) new_7_days, '
    . 'SUM(first_seen_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY) new_30_days '
    . 'FROM rostermate_installations'
)->fetch();
$activity = $pdo->query(
    'SELECT heartbeat_date date, COUNT(*) installations, SUM(heartbeat_count) syncs '
    . 'FROM rostermate_heartbeat_daily WHERE heartbeat_date >= UTC_DATE() - INTERVAL 29 DAY '
    . 'GROUP BY heartbeat_date ORDER BY heartbeat_date'
)->fetchAll();
echo json_encode([
    'generated_at' => gmdate(DATE_ATOM),
    'total' => (int)$counts['total'],
    'active_7_days' => (int)$counts['active_7_days'],
    'active_30_days' => (int)$counts['active_30_days'],
    'active_90_days' => (int)$counts['active_90_days'],
    'new_7_days' => (int)$newInstallations['new_7_days'],
    'new_30_days' => (int)$newInstallations['new_30_days'],
    'platforms' => $platforms,
    'versions' => $versions,
    'activity' => $activity,
]);
