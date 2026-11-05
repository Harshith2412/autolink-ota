// OpenSSL access layer.
// Normal builds include the real OpenSSL 3 headers (libssl-dev / openssl@3).
// The offline sandbox used to develop this project had libcrypto.so.3 but no
// headers, so this falls back to declaring the few stable, public OpenSSL 3
// C ABI functions the ECU uses. All cryptography is still performed by
// OpenSSL; nothing here implements an algorithm.
#pragma once

#if __has_include(<openssl/evp.h>)
#include <openssl/evp.h>
#define AUTOLINK_OPENSSL_REAL_HEADERS 1
#else
#include <cstddef>
extern "C" {
typedef struct evp_md_ctx_st EVP_MD_CTX;
typedef struct evp_md_st EVP_MD;
typedef struct evp_pkey_st EVP_PKEY;
typedef struct engine_st ENGINE;
typedef struct evp_pkey_ctx_st EVP_PKEY_CTX;
const EVP_MD* EVP_sha256(void);
EVP_MD_CTX* EVP_MD_CTX_new(void);
void EVP_MD_CTX_free(EVP_MD_CTX* ctx);
int EVP_DigestInit_ex(EVP_MD_CTX* ctx, const EVP_MD* type, ENGINE* impl);
int EVP_DigestUpdate(EVP_MD_CTX* ctx, const void* d, size_t cnt);
int EVP_DigestFinal_ex(EVP_MD_CTX* ctx, unsigned char* md, unsigned int* s);
EVP_PKEY* EVP_PKEY_new_raw_public_key(int type, ENGINE* e, const unsigned char* pub, size_t len);
void EVP_PKEY_free(EVP_PKEY* pkey);
int EVP_DigestVerifyInit(EVP_MD_CTX* ctx, EVP_PKEY_CTX** pctx, const EVP_MD* type, ENGINE* e,
                         EVP_PKEY* pkey);
int EVP_DigestVerify(EVP_MD_CTX* ctx, const unsigned char* sig, size_t siglen,
                     const unsigned char* tbs, size_t tbslen);
}
#define EVP_PKEY_ED25519 1087 /* NID_ED25519 */
#define AUTOLINK_OPENSSL_REAL_HEADERS 0
#endif
