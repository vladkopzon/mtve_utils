#include <stdio.h>
#include <stdlib.h>
#include <getopt.h>
#include <stdbool.h>


/* Flag set by ‘--verbose’. */
//static int verbose_flag;

int main (int argc, char **argv)
{
  int opt;
  bool address_is_set = false;
  bool cfgfile_is_set = false;
  char * ipaddress   = "";
  char * cfgfilename = "";

  static struct option long_options[] =
    {
     {"ip",           required_argument, 0, 'a'},
     {"config_file",  required_argument, 0, 'f'},
     {0, 0, 0, 0}
    };
  int option_index = 0;

  while (1)
    {
      opt = getopt_long (argc, argv, "a:f:",
                         long_options, &option_index);

      /* Detect the end of the options. */
      if (opt == -1)
        break;

      switch (opt)
        {
        case 'a':
          address_is_set = true;
          ipaddress = optarg;
          break;

        case 'f':
          cfgfile_is_set = true;
          cfgfilename    = optarg;
          break;

        default:
          abort ();
        }
    }

  if (! cfgfile_is_set) {
    printf("usage\n");
  }
  else {
    printf("[%s-%s]\n", cfgfilename, ipaddress);
  }
  if (address_is_set) {

  }
  
  exit (0);
}
