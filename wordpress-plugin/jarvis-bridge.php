<?php
/**
 * Plugin Name: Jarvis Bridge
 * Description: Uploads docx/PDF/images from wp-admin straight to your local
 * Jarvis assistant, which turns them into a ready-to-review WordPress draft
 * (title, body, featured image) — Jarvis never publishes it, that's always
 * done by hand from this site's own editor.
 * Version: 1.0.0
 *
 * Deliberately thin: this file only renders a settings/upload page and
 * loads assets/upload.js, which POSTs directly from the browser to the
 * Jarvis backend's own LAN address (see JARVIS_OPTION_BACKEND_URL below) —
 * no PHP-side HTTP client, no business logic, nothing this plugin needs to
 * process or store beyond the two settings fields. All real work (file
 * conversion, browser automation, draft creation) happens on the Jarvis
 * side — see modules/wordpress_bridge/ in the Jarvis backend repo.
 */

if (!defined('ABSPATH')) {
    exit; // No direct access.
}

define('JARVIS_OPTION_BACKEND_URL', 'jarvis_backend_url');
define('JARVIS_OPTION_API_TOKEN', 'jarvis_api_token');

add_action('admin_menu', 'jarvis_bridge_register_menu');
function jarvis_bridge_register_menu() {
    add_menu_page(
        'Jarvis Bridge',
        'Jarvis',
        'manage_options',
        'jarvis-bridge',
        'jarvis_bridge_render_page',
        'dashicons-format-chat',
        65
    );
}

add_action('admin_init', 'jarvis_bridge_register_settings');
function jarvis_bridge_register_settings() {
    register_setting('jarvis_bridge_settings', JARVIS_OPTION_BACKEND_URL, [
        'type' => 'string',
        'sanitize_callback' => 'esc_url_raw',
        'default' => '',
    ]);
    register_setting('jarvis_bridge_settings', JARVIS_OPTION_API_TOKEN, [
        'type' => 'string',
        'sanitize_callback' => 'sanitize_text_field',
        'default' => '',
    ]);
}

add_action('admin_enqueue_scripts', 'jarvis_bridge_enqueue_assets');
function jarvis_bridge_enqueue_assets($hook) {
    if ($hook !== 'toplevel_page_jarvis-bridge') {
        return;
    }
    wp_enqueue_script(
        'jarvis-bridge-upload',
        plugins_url('assets/upload.js', __FILE__),
        [],
        '1.0.0',
        true
    );
    // The browser (running on the user's own LAN, in wp-admin) posts
    // directly to the Jarvis backend — see core/main.py's
    // POST /api/wordpress/upload. This plugin never proxies the upload
    // through the WordPress server itself, which would need inbound
    // port-forwarding from the hosting provider to the user's home network.
    wp_localize_script('jarvis-bridge-upload', 'jarvisBridgeConfig', [
        'backendUrl' => rtrim((string) get_option(JARVIS_OPTION_BACKEND_URL, ''), '/'),
        'apiToken' => (string) get_option(JARVIS_OPTION_API_TOKEN, ''),
        'siteUrl' => rtrim(site_url(), '/'),
    ]);
}

function jarvis_bridge_render_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    $backend_url = get_option(JARVIS_OPTION_BACKEND_URL, '');
    $has_config = !empty($backend_url) && !empty(get_option(JARVIS_OPTION_API_TOKEN, ''));
    ?>
    <div class="wrap">
        <h1>Jarvis Bridge</h1>
        <p>
            Загрузите docx, PDF или изображения — Jarvis подготовит черновик записи
            (заголовок, текст, главное изображение) и оставит его здесь, в разделе
            «Записи → Черновики», для вашей проверки. <strong>Публикацию Jarvis никогда
            не выполняет сам</strong> — это всегда делаете вы вручную.
        </p>

        <h2>Подключение к Jarvis</h2>
        <form method="post" action="options.php">
            <?php settings_fields('jarvis_bridge_settings'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="jarvis_backend_url">Адрес бэкенда Jarvis</label></th>
                    <td>
                        <input
                            type="url"
                            id="jarvis_backend_url"
                            name="<?php echo esc_attr(JARVIS_OPTION_BACKEND_URL); ?>"
                            value="<?php echo esc_attr($backend_url); ?>"
                            placeholder="http://192.168.1.50:8000"
                            class="regular-text"
                        />
                        <p class="description">
                            LAN-адрес компьютера, на котором запущен Jarvis (см. QR-код/адрес в
                            настройках самого Jarvis).
                        </p>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="jarvis_api_token">Токен доступа</label></th>
                    <td>
                        <input
                            type="password"
                            id="jarvis_api_token"
                            name="<?php echo esc_attr(JARVIS_OPTION_API_TOKEN); ?>"
                            value="<?php echo esc_attr(get_option(JARVIS_OPTION_API_TOKEN, '')); ?>"
                            class="regular-text"
                        />
                    </td>
                </tr>
            </table>
            <?php submit_button('Сохранить подключение'); ?>
        </form>

        <hr />

        <h2>Загрузить материалы</h2>
        <?php if (!$has_config) : ?>
            <p><em>Сначала укажите адрес и токен Jarvis выше.</em></p>
        <?php else : ?>
            <form id="jarvis-upload-form">
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><label for="jarvis-files">Файлы (docx, pdf, изображения)</label></th>
                        <td><input type="file" id="jarvis-files" name="files" multiple required /></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="jarvis-rewrite">Рерайт через ИИ</label></th>
                        <td>
                            <label>
                                <input type="checkbox" id="jarvis-rewrite" name="rewrite_with_ai" />
                                Дать Jarvis отформатировать/переписать текст перед вставкой в черновик
                            </label>
                        </td>
                    </tr>
                </table>
                <p>
                    <button type="submit" class="button button-primary">Отправить Jarvis</button>
                </p>
            </form>
            <div id="jarvis-upload-status" aria-live="polite"></div>
        <?php endif; ?>
    </div>
    <?php
}
