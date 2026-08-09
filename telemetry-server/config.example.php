<?php
declare(strict_types=1);

// Copy this file outside public_html and point ROSTERMATE_CONFIG_FILE at it.
return [
    'dsn' => 'mysql:host=mysql.example.invalid;dbname=database;charset=utf8mb4',
    'db_user' => 'database-user',
    'db_password' => 'change-me',
    'ingest_key' => 'generate-a-long-random-key',
    'admin_key' => 'generate-a-different-long-random-key',
    'installation_hash_secret' => 'generate-a-third-long-random-key',
];
