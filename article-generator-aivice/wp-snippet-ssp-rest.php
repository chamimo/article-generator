<?php
/**
 * SEO SIMPLE PACK のメタフィールドを REST API に登録する
 *
 * 追加先: functions.php または Code Snippets プラグイン
 * ※デバッグ用スニペット（debug/v1/meta）は削除してください
 */
add_action( 'init', function() {
    $ssp_keys = [
        'ssp_meta_title',
        'ssp_meta_description',
    ];
    foreach ( $ssp_keys as $key ) {
        register_post_meta( 'post', $key, [
            'show_in_rest'  => true,
            'single'        => true,
            'type'          => 'string',
            'auth_callback' => function() {
                return current_user_can( 'edit_posts' );
            },
        ] );
    }
} );
