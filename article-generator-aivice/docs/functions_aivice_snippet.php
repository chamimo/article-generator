<?php
/**
 * AIVICE (workup-ai.com) – REST API メタフィールド登録スニペット
 * swell_child の functions.php の末尾に追記してください。
 *
 * 登録するフィールド:
 *   ssp_meta_title                 … SEO SIMPLE PACK タイトル（旧登録名）
 *   ssp_meta_description           … SEO SIMPLE PACK ディスクリプション（旧登録名）
 *   _ssp_post_title                … SEO SIMPLE PACK カスタムタイトル（正式名）
 *   _ssp_post_description          … SEO SIMPLE PACK メタディスクリプション（正式名）
 *   imagefx_prompt                 … アイキャッチ生成プロンプト（確認用）
 *   _swell_post_eye_catch_caption  … SWELL アイキャッチ画像の注釈
 */
add_action( 'init', function () {

    $meta_fields = [
        'ssp_meta_title' => [
            'type'        => 'string',
            'description' => 'SEO SIMPLE PACK タイトル（旧登録名）',
            'single'      => true,
            'default'     => '',
        ],
        'ssp_meta_description' => [
            'type'        => 'string',
            'description' => 'SEO SIMPLE PACK ディスクリプション（旧登録名）',
            'single'      => true,
            'default'     => '',
        ],
        'ssp_meta_ogimage_url' => [
            'type'        => 'string',
            'description' => 'SEO SIMPLE PACK OGP 画像 URL',
            'single'      => true,
            'default'     => '',
        ],
        '_ssp_post_title' => [
            'type'        => 'string',
            'description' => 'SEO SIMPLE PACK カスタムタイトル（正式名）',
            'single'      => true,
            'default'     => '',
        ],
        '_ssp_post_description' => [
            'type'        => 'string',
            'description' => 'SEO SIMPLE PACK メタディスクリプション（正式名）',
            'single'      => true,
            'default'     => '',
        ],
        'imagefx_prompt' => [
            'type'        => 'string',
            'description' => 'アイキャッチ生成プロンプト（確認用）',
            'single'      => true,
            'default'     => '',
        ],
        '_swell_post_eye_catch_caption' => [
            'type'        => 'string',
            'description' => 'SWELL アイキャッチ画像の注釈',
            'single'      => true,
            'default'     => '',
        ],
    ];

    foreach ( $meta_fields as $key => $args ) {
        register_post_meta( 'post', $key, array_merge( $args, [
            'show_in_rest'  => true,
            'auth_callback' => '__return_true',
        ] ) );
    }
} );
