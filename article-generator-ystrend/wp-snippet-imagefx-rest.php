<?php
/**
 * imagefx_prompt カスタムフィールドを REST API に登録する
 *
 * 追加先: functions.php または Code Snippets プラグイン
 */
add_action( 'init', function() {
    register_post_meta( 'post', 'imagefx_prompt', [
        'show_in_rest'  => true,
        'single'        => true,
        'type'          => 'string',
        'auth_callback' => function() {
            return current_user_can( 'edit_posts' );
        },
    ] );
} );
