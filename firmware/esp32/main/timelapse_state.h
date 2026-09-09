#ifndef TIMELAPSE_STATE_H
#define TIMELAPSE_STATE_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
static inline bool tl_parse_u32(const char *s, uint32_t max, uint32_t *out) { uint64_t n=0; if(!*s)return false; for(;*s;s++){if(*s<'0'||*s>'9'||n>(UINT32_MAX-(unsigned)(*s-'0'))/10)return false;n=n*10+(unsigned)(*s-'0');}if(n>max)return false;*out=(uint32_t)n;return true; }
static inline int tl_hex(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
/* Returns 1 present, 0 absent, -1 malformed/duplicate/too large. */
static inline int tl_form_value(const char *body,const char *key,char *out,size_t size){size_t k=strlen(key);bool found=false;for(const char *p=body;*p;){const char *end=strchr(p,'&');if(!end)end=p+strlen(p);if((size_t)(end-p)>k&&!memcmp(p,key,k)&&p[k]=='='){if(found||!size)return -1;found=true;size_t n=0;for(p+=k+1;p<end;p++){char c=*p;if(c=='+')c=' ';else if(c=='%'){int hi=(p+2<end)?tl_hex(p[1]):-1,lo=(p+2<end)?tl_hex(p[2]):-1;if(hi<0||lo<0)return -1;c=(char)(hi*16+lo);p+=2;}if(!c||n+1>=size)return -1;out[n++]=c;}out[n]=0;}p=*end?end+1:end;}return found?1:0;}
static inline uint64_t tl_estimate(uint64_t bytes,uint32_t successful){return successful&&bytes/successful?bytes/successful:512ULL*1024;}
static inline bool tl_capacity_ok(uint64_t free_bytes,uint64_t estimate){return free_bytes>=256ULL*1024*1024&&free_bytes>=estimate+2ULL*1024*1024;}
#endif
