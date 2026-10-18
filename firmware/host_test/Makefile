CFLAGS ?= -O2 -Wall -Wextra -Werror -std=c11
MAIN := ../main

mfcc_parity: mfcc_parity.c $(MAIN)/mfcc.c $(MAIN)/mfcc.h $(MAIN)/generated/selftest_vectors.h
	$(CC) $(CFLAGS) -I$(MAIN) -o $@ mfcc_parity.c $(MAIN)/mfcc.c -lm
	./$@

clean:
	rm -f mfcc_parity

.PHONY: clean
