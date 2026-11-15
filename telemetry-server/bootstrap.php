<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$configFile = getenv('ROSTERMATE_CONFIG_FILE') ?: dirname(__DIR__, 2) . '/rostermate-telemetry-config.php';
if (!is_file($configFile)) {
    http_response_code(500);
    echo json_encode(['error' => 'Server configuration missing']);
    exit;
}
$config = require $configFile;
$pdo = new PDO($config['dsn'], $config['db_user'], $config['db_password'], [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    PDO::ATTR_EMULATE_PREPARES => false,
]);

function supplied_header(string $name): string {
    $serverName = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
    return trim((string)($_SERVER[$serverName] ?? ''));
}

function fail_request(int $status, string $message): never {
    http_response_code($status);
    echo json_encode(['error' => $message]);
    exit;
}

function ensure_report_table(PDO $pdo): void {
    if ($pdo->getAttribute(PDO::ATTR_DRIVER_NAME) === 'sqlite') {
        $pdo->exec('CREATE TABLE IF NOT EXISTS rostermate_error_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, '
            . 'created_at TEXT NOT NULL, installation_hash TEXT NULL, platform TEXT NOT NULL, app_version TEXT NOT NULL, report TEXT NOT NULL)');
    } else {
    $pdo->exec('CREATE TABLE IF NOT EXISTS rostermate_error_reports ('
        . 'id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, created_at DATETIME NOT NULL, installation_hash CHAR(64) NULL, '
        . 'platform VARCHAR(16) NOT NULL, app_version VARCHAR(32) NOT NULL, report MEDIUMTEXT NOT NULL, '
        . 'INDEX idx_created_at (created_at), INDEX idx_installation (installation_hash)'
        . ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
    }
    // Tilføjet efter første udrulning; eksisterende tabeller får kolonnen her.
    try {
        $pdo->query('SELECT ip_hash FROM rostermate_error_reports LIMIT 0');
    } catch (PDOException $e) {
        $pdo->exec('ALTER TABLE rostermate_error_reports ADD COLUMN ip_hash CHAR(64) NULL');
    }
}
