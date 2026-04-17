<?php
/**
 * はた楽ナビ (hataraku-navi.com) – REST API メタフィールド登録スニペット
 * functions.php の末尾に追記してください。
 *
 * 登録するフィールド:
 *   _ssp_post_title       … SEO SIMPLE PACK カスタムタイトル
 *   _ssp_post_description … SEO SIMPLE PACK メタディスクリプション
 *   imagefx_prompt        … アイキャッチ生成プロンプト（確認用）
 */
add_action( 'init', function () {

    $meta_fields = [
        '_ssp_post_title' => [
            'type'         => 'string',
            'description'  => 'SEO SIMPLE PACK カスタムタイトル',
            'single'       => true,
            'default'      => '',
        ],
        '_ssp_post_description' => [
            'type'         => 'string',
            'description'  => 'SEO SIMPLE PACK メタディスクリプション',
            'single'       => true,
            'default'      => '',
        ],
        'imagefx_prompt' => [
            'type'         => 'string',
            'description'  => 'アイキャッチ生成プロンプト（確認用）',
            'single'       => true,
            'default'      => '',
        ],
    ];

    foreach ( $meta_fields as $key => $args ) {
        register_post_meta( 'post', $key, array_merge( $args, [
            'show_in_rest'  => true,
            'auth_callback' => '__return_true',
        ] ) );
    }
} );
