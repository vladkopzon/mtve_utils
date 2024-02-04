#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include <stdint.h>
#include <time.h>
#include <sys/time.h>
#include <math.h>
#ifndef _WIN32
#include <unistd.h>
#endif
#include "profpga.h"
#include "profpga_error.h"
#include "mmi64.h"
#include "mmi64_defines.h"
#include "mmi64_module_upstreamif.h"
#include "mmi64_module_regif.h"
#include "mmi64_module_axi_master.h"
#include "profpga_logging.h"
#include "libconfig.h"
// here we use the mmi64 cross-platform definitions to implement
// a OS (semi-)independent threading
#include "mmi64_crossplatform.h"
#include <inttypes.h>

//Socket
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <arpa/inet.h> //inet_addr
#include <netinet/in.h>
#pragma pack(1)


#include "mtve_headers.h"
//#define ENABLE_ACK_ON_WRITE

// //////////////////////////////////////////////////////////////////////
// (global) default parameters
// //////////////////////////////////////////////////////////////////////
#define VERSION "1.0"
#define MAX_BUFFER_SIZE_EXP 30

#define THREAD_WAIT_TIME_MSECONDS 1000

int parNoConfig = 0;
int parBootUp = 0;
int parShutDown = 0;
int parTime = 30;
int parMaxMessageSize = 1024;
int parMinMessageSize = 64;
int parPickUpMessageSize = 2048;
int parBufferSizeExp = 20;
int parFirstIf = 0;
int parOnlyIf = -1;
int parIfCount = 0;
int parDummyReads = 0;
int parDebug = 0;
int parDebugSwitchIsSet = 0;
int parUseBlockingInit = 0;
int parDisableDataCheck = 0;

#define CHECK(status)  if (status!=E_PROFPGA_OK) { \
  printf(NOW("ERROR: (FPGA): %s\n"), profpga_strerror(status)); \
  return status;  }

char * cfgfilename = "profpga.cfg";  

long long get_elapsed_time(struct timespec start_time)
{
  struct timespec now;
  long long elapsed;
  clock_gettime(CLOCK_MONOTONIC, &now);
  // Calculate the elapsed time in microseconds
  elapsed = (now.tv_sec - start_time.tv_sec) * 1000000000LL + (now.tv_nsec - start_time.tv_nsec)/1000;
  return elapsed;
}

long long get_time_us()
{
  struct timeval tv;

  gettimeofday(&tv, NULL);
  return tv.tv_sec * 1000000LL + tv.tv_usec;
}

void print_performance_stat(long long abs_start, long long t1_saved, int msg_indx, uint64_t cmd_type,
                            long long t1, long long t2, long long t3, long long t4, long long t5)
{
  char * msg_type;
  if (cmd_type  == REGIF_READ) {
    msg_type = " read_perf[us]";
  }
  else {
    msg_type = "write_perf[us]";
  }
  printf("%s[%5d]:prev_cmd=%6d:wait4length=%6d:wait4data=%6d:wait4fpga=%6d:ack2python=%6d:cmd_time=%6d:abs_time=%8d\n",
         msg_type, msg_indx,t1-t1_saved, t2-t1, t3-t2, t4-t3, t5-t4, t3-t2+ t4-t3+ t5-t4, t5-abs_start);
}

int message_handler(const int messagetype, const char *fmt,...)
{
  int n;
  va_list ap;
  
  va_start(ap, fmt);
  n = vfprintf(stdout, fmt, ap);
  va_end(ap);
  return n;
}

mmi64_module_t* get_module_by_id(uint64_t id, mmi64_module_t** xtors, uint32_t xtors_count){
  int i;
  for (i = 0; i < xtors_count; i++) {
    if (id == xtors[i]->id) {
      return xtors[i];
    }
  }
  printf(NOW("ERROR: (FPGA): Undefined xTor ID=0x%08X addressed!\n"), id);
}

mmi64_error_t mmi64_mtve_info_provider(const mmi64_module_t* module, char* str){
  printf ("INFO    : mtv_regif   : MTVe Xtor id [%d] >>>>>>", module->id);
  return E_MMI64_OK;
}

bool is_bit_X_set(uint64_t n, int X) {
    return (n & (1LL << X)) != 0;
}


// //////////////////////////////////////////////////////////////////////
// mmi64_main
// //////////////////////////////////////////////////////////////////////
mmi64_error_t mmi64_main(int argc, char * argv[]) {
  profpga_handle_t* profpga;  // handle to profpga system
  profpga_error_t   status;      // error status used as return value for all profpga function calls

  uint64_t*         payload;
  mmi64_module_t**  identified_reg1;         // identify_by_id can return multiple modules (if same bitfile is used in multiple FPGAs or if same Module ID is used)
  uint32_t          identified_reg1_count;
  mmi64_module_t**  identified_reg2;         // identify_by_id can return multiple modules (if same bitfile is used in multiple FPGAs or if same Module ID is used)
  uint32_t          identified_reg2_count;

  mmi64_module_t**  xtors;         // identify_by_type can return multiple modules
  uint32_t          xtors_count;

  mmi64_module_t*   user_reg1if_module = NULL;  // handle to register module
  mmi64_module_t*   user_reg2if_module = NULL;  // handle to register module
  mmi64_module_t*   user_axi_master_module = NULL;  // handle to AXI master module

  // mmi64 AXI master, needs additional handle
  axi_mmi64_module_t* axi_master = NULL; 
  axi_error_t         axi_status    = E_AXI_OK;

  uint16_t addr = 0;
  uint16_t error_cnt = 0;
  uint32_t test_data_32[256];
  uint32_t rcv_data_32[256];

  enum MMI_OPCODES mmi_opcode;
  int i, k, j;
  
  printf("INFO (FPGA): Using configuration file [%s]\n", cfgfilename);
  //Socket Connection  
  int PORT = 2300;
  struct timespec start_time;
  setbuf(stdout, NULL);

#ifdef HDL_SIM
  // if we run in RTL simulation we set the default parameter
  // and execute the main program
  parTime = 10;                        // option -t
  parNoConfig = 0;                     // option -n
  parBootUp = 0;                       // option -u
  parShutDown = 0;                     // option -d
  parMaxMessageSize = 1024;            // option -m
  parMinMessageSize = 64;             // option -i
  parPickUpMessageSize = 16;           // option -p
  parBufferSizeExp = 16;               // option -b
  parFirstIf = 0;                      // option -s
  parOnlyIf = -1;                      // option -o
  parIfCount = 0;                      // option -r
  parDummyReads = 0;                   // option -g
  parDebugSwitchIsSet = 1;             // option -e is used/unused
  parDebug = 0x00;                     // option -e
  parUseBlockingInit = 0;              // option -B
  parDisableDataCheck = 0;             // option -C
  //return exec_test("profpga.cfg");
#endif
  bool IS_UNIX_SOCKET = true;
  char *hostname = getenv("MTVe_HostAddress"), *hostport = getenv("MTVe_Port");
  /* printf("MTVe_HostAddress: %s\n", hostname ? hostname : "null"); */
  /* printf("MTVe_Port: %s\n", hostport); */
  if (hostname && hostport &&  strcmp(hostname , "127.0.0.1") != 0 ) {
	  IS_UNIX_SOCKET = false;
  }
  
  struct sockaddr_in in_server_address, in_client_address;
  struct sockaddr_un un_server_address, un_client_address;
  // Initialize socket
  int server_socket, client_socket;
  char socket_path[] = SOCKET_FNAME;
  char *socket_name_suffix = getenv("CRUN_MTV_SOCKET_NAME");
  struct timeval timeout;
  // Set the timeout
  char *mtv_socket_init_timeout = getenv("MTV_SOCKET_INIT_TIMEOUT");
  char *mtv_socket_data_timeout = getenv("MTV_SOCKET_DATA_TIMEOUT");
  int socket_init_timeout, socket_data_timeout;
  if (mtv_socket_init_timeout != NULL) {
      // MTV_SOCKET_INIT_TIMEOUT is set, convert it to an integer
      socket_init_timeout = atoi(mtv_socket_init_timeout);
      printf("INFO (FPGA): SOCKET_INIT_TIMEOUT=%d[sec]\n", socket_init_timeout);
  } else {
      // MTV_SOCKET_INIT_TIMEOUT is not set, use a default value
      socket_init_timeout = SOCKET_INIT_TIMEOUT;
  }
  if (mtv_socket_data_timeout != NULL) {
      // MTV_SOCKET_DATA_TIMEOUT is set, convert it to an integer
      socket_data_timeout = atoi(mtv_socket_data_timeout);
      printf("INFO (FPGA): SOCKET_DATA_TIMEOUT=%d[sec]\n", socket_data_timeout);
  } else {
      // MTV_SOCKET_DATA_TIMEOUT is not set, use a default value
      socket_data_timeout = SOCKET_DATA_TIMEOUT;
  }
  timeout.tv_sec  = socket_init_timeout;
  timeout.tv_usec = 0;

  if (!socket_name_suffix) {
    socket_name_suffix = SOCKET_UNNAMED;
  }
  strcat(socket_path, socket_name_suffix);
  if (IS_UNIX_SOCKET) {
    printf("INFO (FPGA): Initializing UNIX_SOCKET [%s]\n", socket_path);
    unlink(socket_path);
    memset(&un_server_address, 0, sizeof(un_server_address));
    un_server_address.sun_family = AF_UNIX;
    strncpy(un_server_address.sun_path, socket_path, sizeof(un_server_address.sun_path) - 1);
  }else{
    printf("INFO (FPGA): Initializing INET_SOCKET\n");
    in_server_address.sin_family = AF_INET;
    if (hostname && hostport && (strcmp(hostname , "null") != 0) ) {
      printf("INFO (FPGA): Open socket by environmental variable request \n");
      printf("INFO (FPGA): MTVe_HostAddress: %s\n", hostname ? hostname : "null");
      printf("INFO (FPGA): MTVe_Port: %s\n", hostport);
      // Prepare the server address
      in_server_address.sin_family = AF_INET;
      in_server_address.sin_addr.s_addr = inet_addr(hostname);
      in_server_address.sin_port = htons(atoi(hostport));
    }else{
      printf("INFO (FPGA): Open socket by defult port , address  \n");
      printf("INFO (FPGA): MTVe_HostAddress: %s\n", INADDR_ANY);
      printf("INFO (FPGA): MTVe_Port: %d\n", PORT);
      in_server_address.sin_addr.s_addr = INADDR_ANY;
      in_server_address.sin_port = htons(PORT);
    }
  }

  // Create socket
  if (IS_UNIX_SOCKET)
	server_socket = socket(AF_UNIX, SOCK_STREAM, 0);
  else
	server_socket = socket(AF_INET, SOCK_STREAM, 0);
  if (server_socket == -1) {
    printf(NOW("ERROR:  (FPGA): Socket creation failed"));
    exit(EXIT_FAILURE);
  }

  if (setsockopt(server_socket, SOL_SOCKET, SO_RCVTIMEO, (char *)&timeout, sizeof(timeout)) < 0) {
      perror("ERROR:  (FPGA): Socket set option RX failed\n");
      exit(EXIT_FAILURE);
  }
  
  if (setsockopt(server_socket, SOL_SOCKET, SO_SNDTIMEO, (char *)&timeout, sizeof(timeout)) < 0) {
      perror("ERROR:  (FPGA): Socket set option TX failed\n");
      exit(EXIT_FAILURE);
  }

  // Bind the socket
  if (IS_UNIX_SOCKET) {
	  if (bind(server_socket, (struct sockaddr*)&un_server_address, sizeof(un_server_address)) == -1) {
		printf(NOW("ERROR:  (FPGA): Socket binding failed"));
		exit(EXIT_FAILURE);
	  }
  }else{
	  if (bind(server_socket, (struct sockaddr*)&in_server_address, sizeof(in_server_address)) == -1) {
		printf(NOW("ERROR:  (FPGA): Socket binding failed"));
		exit(EXIT_FAILURE);
	  }  
  }

  // Listen for connections
  if (listen(server_socket, 1) == -1) {
    printf(NOW("ERROR:  (FPGA): Socket listening failed"));
        exit(EXIT_FAILURE);
    }

  printf("INFO (FPGA): Waiting for a connection...\n");
  // Accept a connection from the Python script
  if (IS_UNIX_SOCKET) {
	  socklen_t client_address_length = sizeof(un_client_address);
	  client_socket = accept(server_socket, (struct sockaddr*)&un_client_address, &client_address_length);
  }
  else
  {
	  socklen_t client_address_length = sizeof(in_client_address);
	  client_socket = accept(server_socket, (struct sockaddr*)&in_client_address, &client_address_length);
  }
  if (client_socket == -1) {
      perror("ERROR: (FPGA): Socket acceptance failed");
      exit(EXIT_FAILURE);
  }

  if (socket_data_timeout >= 0) {
      timeout.tv_sec  = socket_data_timeout; //increasing timeout for data phase
      if (setsockopt(server_socket, SOL_SOCKET, SO_RCVTIMEO, (char *)&timeout, sizeof(timeout)) < 0) {
          perror("ERROR:  (FPGA): Socket set option RX failed\n");
          exit(EXIT_FAILURE);
      }
  
      if (setsockopt(server_socket, SOL_SOCKET, SO_SNDTIMEO, (char *)&timeout, sizeof(timeout)) < 0) {
          perror("ERROR:  (FPGA): Socket set option TX failed\n");
          exit(EXIT_FAILURE);
      }
      printf("INFO (FPGA): Socket timeout for data phase is set to %d [sec]\n", socket_data_timeout);
  }
  else {
      printf("INFO (FPGA): Socket timeout for data phase is disabled by either SOCKET_DATA_TIMEOUT or ENV(MTVE_SOCKET_DATA_TIMEOUT).\n");
  }

  printf("INFO (FPGA): Connection established.\n");
  unlink(socket_path);
  /* from manpage:
    The usual UNIX close-behind
    semantics apply; the socket can be unlinked at any time and will
    be finally removed from the filesystem when the last reference to
    it is closed.
   */

  // installing message handler
  int mh_status = profpga_set_message_handler(message_handler);
  if (mh_status!=0) {
    printf("ERROR: (FPGA): Failed to install message handler (code %d)\n", mh_status);
    return mh_status;
  }
  
  // connect to system
  printf("INFO (FPGA): Open connection to profpga platform...\n");  // cannot use NOW() macro because required MMI-64 domain handle has not been initialized
  
  status = profpga_open (&profpga, cfgfilename);
  if (status!=E_PROFPGA_OK) { 
    printf("ERROR: (FPGA): Failed connect to PROFPGA system (%s)\n", profpga_strerror(status));
    return status;
  }
  
#ifdef HDL_SIM
  // for HDL simulation: perform configuration as done by profpga_run --up
  printf(NOW("INFO (FPGA): Bring up system.\n"));
  status = profpga_up(profpga);
  CHECK(status);
#endif

  status = mmi64_info_provider_register(
                                        profpga->mmi64_domain,
                                        MTV_XTOR_TYPE,
                                        mmi64_mtve_info_provider);
  CHECK(status);
  

  uint64_t* mmi_read_buffer;
  mmi_read_buffer = (uint64_t*)malloc(MMI_MAX_MSG_LENGTH * sizeof(uint64_t));
  if (mmi_read_buffer == NULL) {
    printf(NOW("ERROR: (FPGA): Memory allocation failed.\n"));
    exit(EXIT_FAILURE);
  }
  int       message_count = 1;
  uint64_t  msg_length;
  uint64_t* read_data64;
  bool      test_not_done = 1;

  long long abs_start;
  long long t1, t1_saved;       /* before socket read from python*/
  long long t2;                 /* after socket length read */
  long long t3;                 /* after socket message read */
  long long t4;                 /* after FPGA call returned */
  long long t5;                 /* after socket write to python */
  
  while (test_not_done) {
#ifdef PERF_PRINTS
    t1_saved = t1;
    t1 = get_time_us();
    if (message_count == 1) {
      t1_saved = t1;
      abs_start = t1;
      //printf(" _perf      IDX  : READY: LEN  : DATA : FPGA : WRITE: L2WB  : ABS_TIME\n");
    }
#endif
    ssize_t bytes_received;
    if (IS_UNIX_SOCKET)
      bytes_received = read(client_socket, &msg_length, sizeof(msg_length));
    else
      bytes_received = recv(client_socket, &msg_length, sizeof(msg_length), 0);


#ifdef PERF_PRINTS
    t2 = get_time_us();
#endif
    
    if (bytes_received == -1) {
      printf(NOW("ERROR: (FPGA): Failed to receive data. Exiting...\n"));
      exit(EXIT_FAILURE);
    } else if (bytes_received == 0) {
      printf(NOW("ERROR: (FPGA): Client disconnected abnormally on length read!. Exiting...\n"));
      exit(EXIT_FAILURE);
    }
    msg_length = be64toh(msg_length);
    payload = (uint64_t*)malloc(msg_length * sizeof(uint64_t));
    if (payload == NULL) {
      printf(NOW("ERROR: (FPGA): Memory allocation failed. Exiting\n"));
      exit(EXIT_FAILURE);
    }
    memset(payload, 0, msg_length*sizeof(uint64_t));
    if (IS_UNIX_SOCKET) 
      bytes_received = read(client_socket, payload, msg_length*sizeof(uint64_t));
    else
      bytes_received = recv(client_socket, payload, msg_length*sizeof(uint64_t), 0);


#ifdef PERF_PRINTS
    t3 = get_time_us();
#endif
    if (bytes_received == -1) {
      printf(NOW("ERROR: (FPGA): Failed to receive data. Exiting...\n"));
      exit(EXIT_FAILURE);
    } else if (bytes_received == 0) {
      printf(NOW("ERROR: (FPGA): Client disconnected abnormally on data read!. Exiting...\n"));
      exit(EXIT_FAILURE);
    }
    
    int i;
    for (i = 0; i < msg_length; i++) {
      payload[i] = be64toh(payload[i]);
    }

    bool no_print = is_bit_X_set(payload[MMI_OPCODE_IDX], MMI_OPCODE_NO_PRINT_MASK);
    payload[MMI_OPCODE_IDX] &= -1LL & ~(1LL << MMI_OPCODE_NO_PRINT_MASK);
    mmi_opcode = payload[MMI_OPCODE_IDX];
       
    if (!no_print) {
        printf(NOW("INFO (FPGA): Received new MMI message #%d [%d qwords (%d)B]: {"),
               message_count, msg_length, bytes_received);
        for (i = 0; i < msg_length; i++) {
            printf("0x%" PRIX64 " ", payload[i]);
        }
        printf("}\n");
    }

    if (mmi_opcode == STOP) {
      //test is done
      printf(NOW("INFO (FPGA): Test termination request received\n"));
      test_not_done = 0;
#ifdef PERF_PRINTS
      t4 = get_time_us();
#endif
#ifdef PERF_PRINTS
      print_performance_stat(abs_start, t1_saved, message_count, mmi_opcode, t1, t2, t3, t4, t4);
#endif
    }
    else if (mmi_opcode == SCAN) { //SCAN request
      // scan for MMI64 modules
      printf(NOW("INFO (FPGA): Scan hardware...\n"));
      status = mmi64_identify_scan(profpga->mmi64_domain);
      CHECK(status);
      
      // print scan results
      status = mmi64_info_print(profpga->mmi64_domain);
      CHECK(status);
      
      status = mmi64_identify_by_type(profpga->mmi64_domain, MTV_XTOR_TYPE, &xtors, &xtors_count);
      CHECK(status);
      uint32_t xtor_array [MTV_MAX_XTORS];
      for (i = 0; i < MTV_MAX_XTORS; i++) {
        if (i < xtors_count) {
          xtor_array[i] = xtors[i]->id;
          printf("Scanned xTor id: %d\n", xtor_array[i]);
        }
        else {
          xtor_array[i] = 0x00000000;
        }
      }
#ifdef PERF_PRINTS
      t4 = get_time_us();
#endif
      // Send the response back to the Python:
      ssize_t bytes_sent;
      if (IS_UNIX_SOCKET) 
        bytes_sent = write(client_socket, xtor_array, sizeof(xtor_array));
      else
        bytes_sent = send(client_socket, xtor_array, sizeof(xtor_array), 0);
      

#ifdef PERF_PRINTS
      t5 = get_time_us();
#endif
      if (bytes_sent == -1) {
        printf(NOW("ERROR: (FPGA): Failed to send data back to python"));
        exit(EXIT_FAILURE);
      }
      printf("INFO (FPGA): scan execution completed\n");
#ifdef PERF_PRINTS
      print_performance_stat(abs_start, t1_saved, message_count, mmi_opcode, t1, t2, t3, t4, t5);
#endif
    }
    else {
      switch (mmi_opcode) {
         case REGIF_WRITE: {             /* write */
             if (!no_print) {
                 printf(NOW("INFO (FPGA): Sending mmi64 config write message to xTor ID:%d, burst_size=%d\n"),
                        payload[MMI_XTOR_ID_IDX], payload[MMI_LENGTH_IDX]);
             }
           //was: mmi64_regif_write_64_ack
           status = mmi64_regif_write_64_noack(get_module_by_id(payload[MMI_XTOR_ID_IDX], xtors, xtors_count),
                                             payload[MMI_ADDR_IDX], payload[MMI_LENGTH_IDX], &payload[MMI_DATA_IDX]);		 
           CHECK(status);
#ifdef PERF_PRINTS
           t4 = get_time_us();
#endif
#ifdef ENABLE_ACK_ON_WRITE
           // Send the ACK back to the Python script. No meaning to the data.
           int bytes_to_send = sizeof(read_data64);
           ssize_t bytes_sent;
           if (IS_UNIX_SOCKET)  
             bytes_sent = write(client_socket, read_data64, bytes_to_send);
           else
             bytes_sent = send(client_socket, read_data64, bytes_to_send, 0);
           
           if (bytes_sent != bytes_to_send) {
             printf(NOW("ERROR: (FPGA): Failed to send data back to python"));
             exit(EXIT_FAILURE);
           }
#endif
#ifdef PERF_PRINTS
           t5 = get_time_us();
#endif
#ifdef PERF_PRINTS
           print_performance_stat(abs_start, t1_saved, message_count, mmi_opcode, t1, t2, t3, t4, t5);
#endif
           break;
         } 
         case REGIF_READ:{              /* read */
           read_data64 = (uint64_t*)malloc(payload[MMI_LENGTH_IDX] * sizeof(uint64_t));
           if (read_data64 == NULL) {
             printf(NOW("ERROR: (FPGA): Memory allocation failed.\n"));
             exit(EXIT_FAILURE);
           }
           memset(read_data64, 0, payload[MMI_LENGTH_IDX]*sizeof(read_data64));
           status = mmi64_regif_read_64(get_module_by_id(payload[MMI_XTOR_ID_IDX], xtors, xtors_count),
                                        payload[MMI_ADDR_IDX], payload[MMI_LENGTH_IDX], read_data64);
           CHECK(status);

#ifdef PERF_PRINTS
           t4 = get_time_us();
#endif
           // Send the response back to the Python script
           int bytes_to_send = payload[MMI_LENGTH_IDX]*sizeof(read_data64);
           ssize_t bytes_sent;
           if (IS_UNIX_SOCKET) 
             bytes_sent = write(client_socket, read_data64, bytes_to_send);
           else
             bytes_sent = send(client_socket, read_data64, bytes_to_send, 0);

           if (bytes_sent != bytes_to_send) {
             printf(NOW("ERROR: (FPGA): Failed to send data back to python"));
             exit(EXIT_FAILURE);
           }
#ifdef PERF_PRINTS
           t5 = get_time_us();
#endif
           if (!no_print) {
               printf(NOW("INFO (FPGA): Response data: #%d {"), message_count);
               for (k=0;k<payload[MMI_LENGTH_IDX];k++) {
                   printf("0x%" PRIX64 " ", read_data64[k]);
               }
               printf("}\n");
           }
#ifdef PERF_PRINTS
           print_performance_stat(abs_start, t1_saved, message_count, mmi_opcode, t1, t2, t3, t4, t5);
#endif
           free (read_data64);
           break;
         }
         case READ:{              /* read */
             if (!no_print) {
                 printf(NOW("INFO (FPGA): Sending mmi64 read message to xTor ID:%d, burst_size=%d\n"),
                        payload[MMI_XTOR_ID_IDX], payload[MMI_LENGTH_IDX]);
             }
             memset(mmi_read_buffer, 0, MMI_MAX_MSG_LENGTH * sizeof(uint64_t));
             status = mmi64_read(profpga->mmi64_domain,
                                 get_module_by_id(payload[MMI_XTOR_ID_IDX], xtors, xtors_count)->addr,
                                 mmi_read_buffer, MMI_MAX_MSG_LENGTH);
           
             CHECK(status);
#ifdef PERF_PRINTS
             t4 = get_time_us();
#endif
             if (!no_print) {
                 printf(NOW("Read DATA: "));
                 for (k=0;k<MMI_MAX_MSG_LENGTH;k++) {
                     printf("0x%" PRIX64 " ", mmi_read_buffer[k]);
                 }
                 printf("\n");
             }
           // Send the response back to the Python script
             ssize_t bytes_sent;
             if (IS_UNIX_SOCKET) 
                 bytes_sent = write(client_socket, mmi_read_buffer, MMI_MAX_MSG_LENGTH * sizeof(uint64_t));
             else
                 bytes_sent = send(client_socket, mmi_read_buffer, MMI_MAX_MSG_LENGTH * sizeof(uint64_t), 0);
             
             if (bytes_sent == -1) {
                 printf(NOW("ERROR: (FPGA): Failed to send data back to python"));
                 exit(EXIT_FAILURE);
             }
#ifdef PERF_PRINTS
           t5 = get_time_us();
#endif
#ifdef PERF_PRINTS
           print_performance_stat(abs_start, t1_saved, message_count, mmi_opcode, t1, t2, t3, t4, t5);
#endif
           break;
         }
         case WRITE:{              /* write */
             if (!no_print) {
                 printf(NOW("INFO (FPGA): Sending mmi64 write message to xTor ID:%d, burst_size=%d\n"),
                        payload[MMI_XTOR_ID_IDX], payload[MMI_LENGTH_IDX]);
             }

             mmi64_data_t msg [33]; // your message buffer
             uint16_t payload_len; // your payload length
             payload_len = 8;
             msg[0] = mmi64_create_header(0x10 /*CMD*/, 0x00 /*PARAM*/, payload_len, 64 /*TAG*/);
             for(i=0;i<payload_len;i++) msg[i+1] = i;
             status = mmi64_write(profpga->mmi64_domain,
                                  get_module_by_id(payload[MMI_XTOR_ID_IDX], xtors, xtors_count)->addr,
                                  msg);
             CHECK(status);
#ifdef PERF_PRINTS
           t5 = get_time_us();
#endif
#ifdef PERF_PRINTS
           print_performance_stat(abs_start, t1_saved, message_count, mmi_opcode, t1, t2, t3, t4, t5);
#endif
           break;
         }
/*          case RESET:{              /\* resetting mmi64 domain *\/ */
/*            printf(NOW("INFO (FPGA): Resetting mmi64 domain")); */
/*            profpga_close(&profpga); */

/*            // connect to system */
/*            printf("Open connection to profpga platform again...\n");  // cannot use NOW() macro because required MMI-64 domain handle has not been initialized */
  
/*            status = profpga_open (&profpga, cfgfilename); */
/*            if (status!=E_PROFPGA_OK) {  */
/*              printf("ERROR: (FPGA): Failed connect to PROFPGA system (%s)\n", profpga_strerror(status)); */
/*              return status; */
/*            } */
  
/* #ifdef HDL_SIM */
/*            // for HDL simulation: perform configuration as done by profpga_run --up */
/*            printf(NOW("INFO (FPGA): Bring up system.\n")); */
/*            status = profpga_up(profpga); */
/*            CHECK(status); */
/* #endif */

/*            status = mmi64_info_provider_register( */
/*                                                  profpga->mmi64_domain, */
/*                                                  MTV_XTOR_TYPE, */
/*                                                  mmi64_mtve_info_provider); */
/*            CHECK(status); */
/*            break; */
/*          } */
        default:{
           printf("ERROR: (FPGA): Wrong opcode [%d] received!!!\n", mmi_opcode);
           exit(EXIT_FAILURE);
         }
      }
    }
    message_count++;
  }
  
  free (mmi_read_buffer);
  // Close the sockets
  close(client_socket);
  close(server_socket);
  if (IS_UNIX_SOCKET)
    unlink(socket_path);
  
#ifdef HDL_SIM  
    printf(NOW("SIMULATION FINISHED SUCCESSFULLY. Closing connection...\n"));
    unlink(socket_path);
#endif  
    return profpga_close(&profpga);
}

// //////////////////////////////////////////////////////////////////////
// wrapper to access profpga system
// //////////////////////////////////////////////////////////////////////

#ifndef HDL_SIM
void usage() {
  printf ("Usage: mtve_run_fpga [-c <config_file>] [-q] [-debug]\n");
  printf ("Initializes mmi64 socket interface to feed the FPGA from the MTVe.\n\n");
  printf ("[options] are:\n");
  printf ("  -c <config_file>      config file\n");
  printf ("  -q                    quit without actul run\n");
  printf ("  -debug                detailed MMI message information\n");
/*
  printf ("  -t <time>      Test period in seconds (default is %i)\n", parTime);
  printf ("                 A value of -1 means endless testing.\n");
  printf ("  -m <size>      The maximum size of MMI64 messages in 64-bit words to be used by the upstream interface (default is %d)\n", parMaxMessageSize);
  printf ("  -i <size>      The minimum size of MMI64 messages in 64-bit words to be used by the upstream interface (default is %d)\n", parMinMessageSize);
  printf ("  -p <size>      The size of 64-bit words which will be picked up from the FIFO (default is %d)\n", parPickUpMessageSize);
  printf ("  -b <size_exp>  The receive FIFO size in 2^size_exp 64-bit words (default is %d, maximum is %d)\n", parBufferSizeExp, MAX_BUFFER_SIZE_EXP);
  printf ("  -f <number>    The id of the first upstream interface to test.\n");
  printf ("  -r <number>    The number of upstream threads which should be started in parallel.\n");
  printf ("                 A value of 0 starts an upstream thread for each found upstream module (default is %d)\n", parIfCount);
  printf ("  -o <number>    The id of the only interface to test. Same as '-f <number> -r 1'.\n");
  printf ("  -g             Perform additional register read accesses within the main thread to stress the system even more\n");
  printf ("  -e <verbosity> Add debug verbosity after configuring the system (default is 0x%08x)\n", parDebug);
  printf ("  -n             Do not boot-up/shutdown the system. Just connect to the FPGAs and run the test.\n");
  printf ("  -u             Only boot-up system and exit.\n");
  printf ("  -d             Only shut-down system and exit.\n");
  printf ("  -B             Use mmi64_upstreamif_blocking_init() instead of mmi64_upstreamif_init()\n");
  printf ("  -C             Disable data check (for performance measurement)\n");
*/
  exit (-1);
}
#else
void usage() {}
#endif


// //////////////////////////////////////////////////////////////////////
// main()
// //////////////////////////////////////////////////////////////////////

#ifndef HDL_SIM

#include <getopt.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char * argv[])
{
    char * config = NULL;
    char * rtconfig = "profpga_runtime.cfg";
    int c;
    bool quit = false;

    printf ("\n");
    printf ("INFO (FPGA): Version " VERSION " - mtve_run_fpga build " __DATE__ " " __TIME__ "\n");
    printf ("\n");

    while ((c = getopt(argc, argv, "c:q")) != -1) {
        switch (c) {
        case 'c':
            config = optarg;
            break;
        case 'q':
            quit = true;
            break;
        case '?':
            usage();
            return 1;
        default:
            abort();
        }
    }

    if (config != NULL) {
        cfgfilename = config;
    }
    else {
        cfgfilename = rtconfig;
    }

    if (quit) {
        printf("INFO (FPGA): Quiting without actual run (dute to '-q' cmd line option).\n");
    }
    else {
        return  mmi64_main(argc, argv);
    }
}



/* int main(int argc, char * argv[]) */
/* { */
/*  // if we run against real hardware the command line arguments become valid */
/*   int i, status; */
/*   char * ipaddress; */
/*   char * rtconfig = "profpga_runtime.cfg"; */
  
/*   printf ("\n"); */
/*   printf ("Version " VERSION " - mtve_run_fpga build " __DATE__ " " __TIME__ "\n"); */
/*   printf ("\n"); */

/*   // get config file name */
/*   if (argc < 2) usage(); */
/*   cfgfilename = argv[1]; */
/*   if (argc > 2) {              /\* substitute ipaddress in config file, when provided *\/ */
/*     ipaddress = argv[2]; */
/*     char shell_cmd[300]; */
/*     sprintf(shell_cmd, "sed 's|__PROFPGA_NAME__|%s|' %s > %s", ipaddress, cfgfilename, rtconfig); */
/*     //printf("%s", shell_cmd); */
/*     printf("INFO (FPGA): patching config file with runtime system name [%s].\n", ipaddress); */
/*     system(shell_cmd); */
/*     cfgfilename = rtconfig; */
/*   } */

/*   /\* // parse command line options *\/ */
/*   /\* i = 2; *\/ */
/*   /\* while (i < argc) { *\/ */
/*   /\*   if (argv[i][0] != '-') usage(); *\/ */
/*   /\*   switch (argv[i][1]) { *\/ */
/*   /\*   case 'n': parNoConfig = 1; break; *\/ */
/*   /\*   case 'u': parBootUp = 1; break; *\/ */
/*   /\*   case 'd': parShutDown = 1; break; *\/ */
/*   /\*   case 'g': parDummyReads = 1; break; *\/ */
/*   /\*   case 'B': parUseBlockingInit = 1; break; *\/ */
/*   /\*   case 'C': parDisableDataCheck = 1; break; *\/ */
/*   /\*   case 't': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parTime = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'm': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parMaxMessageSize = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'i': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parMinMessageSize = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'b': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parBufferSizeExp = atoi (argv[i+1]); *\/ */
/*   /\*     if (parBufferSizeExp > MAX_BUFFER_SIZE_EXP) *\/ */
/*   /\*       parBufferSizeExp = MAX_BUFFER_SIZE_EXP; *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'f': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parFirstIf = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'r': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parIfCount = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'o': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parOnlyIf = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'p': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parPickUpMessageSize = atoi (argv[i+1]); *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   case 'e': *\/ */
/*   /\*     if (i+1 >= argc) usage(); *\/ */
/*   /\*     parDebug = (int) strtol (argv[i+1], (char **)NULL, 0); *\/ */
/*   /\*     parDebugSwitchIsSet = 1; *\/ */
/*   /\*     i ++; *\/ */
/*   /\*     break; *\/ */
/*   /\*   default: usage(); *\/ */
/*   /\*   } *\/ */
/*   /\*   i ++; *\/ */
/*   /\* } *\/ */

/*   /\* // check if we do not have multiple modes *\/ */
/*   /\* i = 0; *\/ */
/*   /\* if (parNoConfig) i ++; *\/ */
/*   /\* if (parBootUp) i ++; *\/ */
/*   /\* if (parShutDown) i ++; *\/ */
/*   /\* if (i > 1) { *\/ */
/*   /\*   printf ("Error: command line options -n, -u and -d cannot be used at the same time\n"); *\/ */
/*   /\*   return -1; *\/ */
/*   /\* } *\/ */

/*   return  mmi64_main(argc, argv); */
/* } */

#endif
