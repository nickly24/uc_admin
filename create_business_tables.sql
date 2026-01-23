-- Бизнес-таблицы для вариантов, заказов и пользователей
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    telegram_id BIGINT UNIQUE NULL,
    username VARCHAR(255) NULL,
    is_admin TINYINT(1) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS code_variants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    uc_value INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    purchase_type ENUM('code', 'auto') NOT NULL,
    active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_variant (uc_value, purchase_type)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    order_type ENUM('code', 'auto') NOT NULL,
    status ENUM('pending', 'paid', 'failed', 'cancelled') DEFAULT 'pending',
    amount DECIMAL(10, 2) DEFAULT 0,
    payment_provider VARCHAR(50) NULL,
    payment_order_id VARCHAR(100) NULL,
    payment_id VARCHAR(100) NULL,
    payment_method VARCHAR(20) NULL,
    payment_url TEXT NULL,
    player_id VARCHAR(32) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_orders_user (user_id),
    KEY idx_orders_status (status),
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    variant_id INT NOT NULL,
    qty INT NOT NULL,
    price_at_purchase DECIMAL(10, 2) NOT NULL,
    KEY idx_order_items_order (order_id),
    CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT fk_order_items_variant FOREIGN KEY (variant_id) REFERENCES code_variants(id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    code_id INT NULL,
    code_value VARCHAR(32) NOT NULL,
    code_text VARCHAR(255) NOT NULL,
    used TINYINT(1) DEFAULT 0,
    delivered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_codes_order (order_id),
    CONSTRAINT fk_user_codes_order FOREIGN KEY (order_id) REFERENCES orders(id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_activations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    player_id VARCHAR(32) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    activation_result TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_auto_activations_order (order_id),
    CONSTRAINT fk_auto_activations_order FOREIGN KEY (order_id) REFERENCES orders(id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
