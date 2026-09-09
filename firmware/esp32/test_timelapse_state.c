#include <assert.h>
#include "main/timelapse_state.h"
int main(void){char b[8];uint32_t n;assert(tl_parse_u32("999999",999999,&n)&&n==999999);assert(!tl_parse_u32("4294967296",UINT32_MAX,&n));assert(tl_form_value("x=a+&y=1","x",b,sizeof b)==1&&!strcmp(b,"a "));assert(tl_form_value("x=%ZZ","x",b,sizeof b)==-1);assert(tl_capacity_ok(300ULL*1024*1024,512*1024));return 0;}
