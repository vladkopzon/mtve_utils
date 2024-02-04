#!/usr/intel/bin/perl5.14.1 -w

##########################################################################
# The script target:                                                     #
# Create one data base with Excel file that contain all data from all    # 
# design units, with all information on Registers and mapping them in    #
# the addrressmap by unique addrresses.                                  #
#                                                                        #
##########################################################################
#                                                                        #
# File:            RegistersProcess.pl                                   #
# Author:          Boris Dikarev                                         #
# Date Created:    18/10/2018                                            #
#                                                                        #
##########################################################################

use strict;
use warnings;
# Standard libraries

#use lib qw(/usr/intel/pkgs/perl/5.14.1-threads/lib64/module/r1/); # will add those dirs to @INC
use lib qw(/usr/intel/pkgs/perl/5.20.1-threads/lib64/module/r1/); # will add those dirs to @INC
use Spreadsheet::XLSX;
#use Spreadsheet::ParseExcel;
use Spreadsheet::WriteExcel;
use Excel::Writer::XLSX;
use Spreadsheet::ParseXLSX;
use List::MoreUtils qw(uniq);
use File::Copy;
use Getopt::Long;
use Data::Dumper;

##########################################################################
# GetOpts Variables
##########################################################################
my $ModelName;
my $debug;
my $IP;
my $Help;
my $VAR;

GetOptions("model=s"         => \$ModelName       ,
           "debug"           => \$debug           ,
           "IP"              => \$IP              ,
           "var=s"           => \$VAR             ,
           "help"            => \$Help          ) || die PrintHelp($0) ;

PrintHelp($0) if (defined $Help);
#PrintHelp($0) if (defined $Help or not defined $ModelName);

##########################################################################
# Global Variables
##########################################################################
my $PERL_HASH_SEED = 0;
my @ColumnArray_all  = ("Owner","Project","Domain","Sub-function","pcie_sw_regs_access[23:23]","cio_sw_regs_access[22:22]","tar_cs[20:19]","tar_port[18:13]","VSEC_name(tar_index)[12:0]",
"Offset","index","Checker1","Register Name","RTL Name","MSB","LSB","Checker2","Default value","Attribute",
"Field Name","Security Level","Power domain","Module Name","CDC Stable","Not HW reg","DRAM addr","Space Size","test_signal_name","IntelRsvd",
"Register Path","space","baseaddress","Name Description","reg name for pdf","field name for pdf","instance","S&R_Group",
"Absolute offs","S&R_Order","signal_name","Full Field Description");

my @ColumnArray  = ("Owner","Project","Domain","Addrmap","Base addr","Offset","index","Checker1","Register Name",
"RTL Name","MSB","LSB","Checker2","Default value","Attribute","Field Name","Security Level","Power domain","Module Name","CDC Stable","Not HW reg","DRAM addr",
"Space Size","test_signal_name","IntelRsvd","Register Path","space","baseaddress","Name Description","reg name for pdf",
"field name for pdf","instance","S&R_Group","Absolute offs","S&R_Order","signal_name","Full Field Description");

my $workbook;
my $worksheet;
my $worksheet1;
my $worksheet2;
my $worksheet3;
my $cell_format1;
my @RegsXLSXArray;
my @RegsXLSXArraySS;
my @RegsXLSXArrayIP;

########### Find the excels files by model. #################
my $FindPath = "$ENV{MR}";

#@RegsXLSXArray = `find $FindPath/rtl/units/car/regs -iname "*DFX_REGS*.xlsx" | grep -v 'gbr_common' | grep -v 'master' | grep -v 'results' | grep -v 'reg_checkers'`;
@RegsXLSXArray = `find $FindPath/rtl/units $FindPath/rtl/proj/$ENV{PRJ} -iname "*reg*.xlsx" | grep -v 'master' | grep -v 'results' | grep -v 'reg_checkers'`;

######## Set local path for internal process of script ( split and create temp excels ). ###############
my $LocalPath = "results/Registers/XLSX";
system("mkdir -p $LocalPath");
my %DefinesHash = GetDefines();
my %VarsHash;
if ($VAR) {
    %VarsHash = GetVars();
}
################    Find the relevant Excels for IP  ################

if ($IP) {
    print "\n\n===== Cheking IP dont_delete Started =====\n";
    my $DDIP;
    chomp(@RegsXLSXArray);
    foreach my $RegsXLSX (@RegsXLSXArray){ 
        $DDIP = 0;
        print "\n", "Cheking If IP Exists In Excel File: " ,$RegsXLSX, "\n";
        my $parser = Spreadsheet::ParseXLSX->new;        
        my $workbook = $parser->parse("$RegsXLSX");
        if ( !defined $workbook ) {
            die $parser->error(), ".\n";
        }
        my $worksheet_count = $workbook->worksheet_count();
        
        for (my $worksheet_idx = 0; $worksheet_idx < $worksheet_count; $worksheet_idx++){
            my $worksheet = $workbook->worksheet($worksheet_idx);
            my $worksheetName = $worksheet->get_name();
            if ($worksheetName eq "dont_delete_IP") {
                $DDIP = 1;
            }
        }
        if ($DDIP) {
            print "Excel Contain IP dont_delete\n";
            push(@RegsXLSXArrayIP , $RegsXLSX);
        }
    }
    print "\n===== Cheking IP dont_delete Completed =====\n\n\n";
}
if ($IP) {
    @RegsXLSXArraySS = SplitSpreadSheets(@RegsXLSXArrayIP);
} 
else {
    @RegsXLSXArraySS = SplitSpreadSheets(@RegsXLSXArray);
}    
print "SplitSpreadSheets Completed\n";
####### Split the required excel files. ########
split_excels(@RegsXLSXArraySS);
print "split_excels Completed\n";

####### Create Final main excel. ########
create_excel("All_Regs");
my $RealRowStart;
my $row_counter = 1;


########### Change to local path ############################
@RegsXLSXArray = `find $LocalPath/ -iname "*.xlsx"`;
chomp(@RegsXLSXArray);
foreach my $RegsXLSX (@RegsXLSXArray){  
################ going through excels files  ################
    my %ColumnsHOA;
    my %columns_name_hash_SW_DB_info;
    my $GrepResult;
    my $NumOfRepeats;
    my $UniqCounter;
    my @Groups;
    my @Groups_SW_DB_info;
    my @Project_SW_DB_info;
    my @SubFunction;
    my @pcie_sw_regs_access;
    my @pcie_sw_regs_access_SW_DB_info;
    my @cio_sw_regs_access;
    my @cio_sw_regs_access_SW_DB_info;
    my @tar_cs;
    my @tar_cs_SW_DB_info;
    my @tar_port;
    my @tar_port_SW_DB_info;
    my @VSEC_name_array;
    my @VSEC_name_array_SW_DB_info;
    my @VSEC_offset_array;
    my @VSEC_Base_array_SW_DB_info;
    my @VSEC_offset_array_SW_DB_info;
    my $VSEC_IDX = 0;
    my $VSEC_name_Value;
    my @VSEC_name_Value_array;
################    Parsing Excel File  ################
    print "\n", "Parsing Excel File: " ,$RegsXLSX, "\n";
    my $parser = Spreadsheet::ParseXLSX->new;
    my $workbook = $parser->parse("$RegsXLSX");
    if ( !defined $workbook ) {
        die $parser->error(), ".\n";
    }
################    Parsing Excel sheet  ################
    my $worksheet = $workbook->worksheet(0);
    print "Parsing WorkSheet: " ,$worksheet->get_name() ,"\n";
    my ( $row_min, $row_max_1 ) = $worksheet->row_range();
    print "row_min , row_max_1: $row_min, $row_max_1\n" if $debug;
    my $row_max = $row_max_1;
################ get row max and RealRowStart ############################   
    my $StartFlag = 0;
    for my $row ( $row_min .. $row_max_1+1 ) {
        my $cell_0 = $worksheet->get_cell($row,0);
        if (!$StartFlag){     
            next unless $cell_0;
        }
        if(not $StartFlag and $cell_0->value() =~ /Owner/){
            $RealRowStart = $row;
            $StartFlag = 1;
            print "RealRowStart: $RealRowStart\n" if $debug;
        }
        if(((not $cell_0) or $cell_0->value() =~ /^$/) and $StartFlag ){
            $row_max = $row;
            last;
        }
    }
    print "Row Max $row_max\n" if $debug;
################    read excel into hash of arrays  ################ 
    my $row_max_counter = $row_max;
    my ( $col_min, $col_max ) = $worksheet->col_range();
    for my $row ( $RealRowStart+1 .. $row_max ) {   #start with an offset of RealRowStart
        my $scrach_flag = 0;
        my $space_line = 0;
        my $regNameScrach;
        my $col = $col_min;
        for(my $idx=0; $idx<=$#ColumnArray;$idx++){
            my $key = $ColumnArray[$idx];           #to fill hashes by order of columns
            my $cell = $worksheet->get_cell( $row, $col );
################# Check if exsits unneccessary columns ################
CHECK_HEADER:
            my $colName = $worksheet->get_cell($RealRowStart ,$col);   #read the headers.
            next unless $colName;
            my $colNameValue = $colName->value();
            my $chekcHeader = 0;
            if (not $colNameValue ~~ @ColumnArray){
                $col++;
                $cell = $worksheet->get_cell( $row, $col );
                $chekcHeader = 1;
            }
            goto CHECK_HEADER if $chekcHeader;

           #next if not exists in col names..   
            if ($cell){ 
                push(@{$ColumnsHOA {$key}}, $cell->value());
                my $spcae_line_cell =0;
                $regNameScrach = $cell->value() if ($key =~ m/Register Name/);
                $scrach_flag = 1 if ( ($cell->value() =~ m/SCRACH_MEMORY/i) or ($cell->value() =~ m/RESERVED_MEMORY/i));
                $spcae_line_cell = $worksheet->get_cell($row,$col) if ($key=~ m/Space Size/i and $scrach_flag);
                $space_line  = $spcae_line_cell->value()  if $spcae_line_cell;                                    
                if ($key =~ m/Default value/ and $cell->value() !~ m/^0x/ and $cell->value() !~ m/^\[/) {
                    my $Var_name_Value = $VarsHash{$cell->value()};
                    print "Var_name_Value: $Var_name_Value\n";
                    $ColumnsHOA{$key}[-1] = $Var_name_Value;
                    #push(@{$ColumnsHOA {$key}},$Var_name_Value);
                }
                if ($key =~ m/Register Name/ and $scrach_flag) {
                    $ColumnsHOA{$key}[-1] = $ColumnsHOA{$key}[-1]."_0";
                }
                elsif ($key =~ m/RTL Name/ and $scrach_flag){
                    $ColumnsHOA{$key}[-1] = $ColumnsHOA{$key}[-1]."_0";
                }
                elsif ($key =~ m/Field Name/ and $scrach_flag){
                    $ColumnsHOA{$key}[-1] = $ColumnsHOA{$key}[-1]."_0";
                }
                elsif ($key =~ m/Full Field Description/){
                    $ColumnsHOA{$key}[-1] =~ s/\"//g;
                    $ColumnsHOA{$key}[-1] =~ s/\n//g;
                }
                $col++;
            }
            else{
                push(@{$ColumnsHOA {$key}},"");
                $col++;
            }    
        }
        if ($scrach_flag == 1) {
            print "\nspace_line  = $space_line\n" if $debug;
            $row_max_counter += $space_line-1;
           ###### push scrach lines by multiplier of space size. ##########
            for (my $scrach_idx =0 ;$scrach_idx < $space_line -1 ; $scrach_idx++){
                ############ runs on rows from 0 to space size. #########
                for(my $scrach_idx_key=0;$scrach_idx_key<=$#ColumnArray;$scrach_idx_key++){                    
                    ##### run on columns names. #####
                    my $scrach_idx_keyName = $ColumnArray[$scrach_idx_key];
                    #### name of col ####
                    if ($scrach_idx_keyName =~ m/Offset/i) {
                        my $hex = sprintf("0x%03X" , hex($ColumnsHOA{$scrach_idx_keyName}[-1]) + 1);
                        push(@{$ColumnsHOA {$scrach_idx_keyName}}, $hex);
                    }
                    elsif ($scrach_idx_keyName =~ m/Index/i) {
                        my $IndexVal = sprintf($ColumnsHOA{$scrach_idx_keyName}[-1]+1);
                        print "\nIndexVal  = $IndexVal\n" if $debug;
                        push(@{$ColumnsHOA{$scrach_idx_keyName}},$IndexVal);
                    }                     
                    elsif ($scrach_idx_keyName =~ m/Register Name/) {
                        push(@{$ColumnsHOA{$scrach_idx_keyName}},$regNameScrach."_".($scrach_idx+1));
                    }
                    elsif ($scrach_idx_keyName =~ m/RTL Name/) {
                        push(@{$ColumnsHOA{$scrach_idx_keyName}},$regNameScrach."_".($scrach_idx+1));
                    }
                    elsif ($scrach_idx_keyName =~ m/Field Name/) {
                        push(@{$ColumnsHOA{$scrach_idx_keyName}},$regNameScrach."_".($scrach_idx+1));
                    } 
                    else {
                        push(@{$ColumnsHOA {$scrach_idx_keyName}}, $ColumnsHOA {$scrach_idx_keyName}[-1]);
                    }
                }
            }
        }
    }
################    read excel spreadsheet "dont_delete"  ################
    $NumOfRepeats = 1;
    if ($IP) {
        $worksheet = $workbook->worksheet("dont_delete_IP");
    }
    else {
        $worksheet = $workbook->worksheet("dont_delete");
    }
    print "Parsing WorkSheet: " ,$worksheet->get_name() ,"\n";
    ( $row_min, $row_max_1 ) = $worksheet->row_range();
    $row_max = $row_max_1;
################ get row max ############## 
    for my $row ( $row_min .. $row_max_1 ) {
        my $cell_0 = $worksheet->get_cell( $row,0);
        if((not $cell_0) or $cell_0->value() =~ /^$/){
            $row_max = $row;
            last;
        }
        print $row, $cell_0->value(),  "\n" if $debug;
    }
################  read columns according to title - first row  ################
    ( $col_min, $col_max ) = $worksheet->col_range();
    my $row = $row_min;
    for my $col ( $col_min .. $col_max ) {
        my $cell = $worksheet->get_cell( $row, $col );
        my %columns_name_hash=( 
        "Sub-function"=>\@SubFunction,
        "pcie_sw_regs_access[23:23]"=>\@pcie_sw_regs_access,
        "cio_sw_regs_access[22:22]"=>\@cio_sw_regs_access,
        "tar_cs[20:19]"=>\@tar_cs,
        "tar_port[18:13]"=>\@tar_port,
        "VSEC_name(tar_index)[12:0]"=>\@VSEC_name_array,
        "Offset_in_VSEC"=>\@VSEC_offset_array
        );

        foreach my $column_name (keys %columns_name_hash){
            if($cell->value() eq $column_name){
                print "Column name: $column_name\n" if $debug;
                for my $sub_row ( $row_min+1 .. $row_max) {
                    $cell = $worksheet->get_cell( $sub_row, $col );
                    print "$sub_row, $col  ", $cell->value(), "\n" if $debug;
                    if(!($cell->value() =~ /^$/)){ 
                        push(@{$columns_name_hash{$column_name}},$cell->value());
                        if ($column_name eq "Sub-function"){
                            $NumOfRepeats++ if not ($cell->value() ~~ @{$ColumnsHOA {'Addrmap'}});
                        }
                    }
                }
            }
        }
    }
    print "Num of Repeates: ", $NumOfRepeats, "\n" if $debug;     
################   find define value   ################
    foreach my $VSEC_name (@VSEC_name_array){
        $VSEC_name =~ s/\s*$//;
        if($VSEC_name =~ m/0[xX][0-9a-fA-F]+/){
            ($VSEC_name_Value) = $VSEC_name =~ /(0[xX][0-9a-fA-F]+)/;
            $GrepResult = "Constant Value, No Need for Grep";
        }
        else{
            $VSEC_name =~ s/^\s+//;
            $VSEC_name =~ s/\s+$//;
            $VSEC_name_Value = $DefinesHash{$VSEC_name};
            #$GrepResult = `grep -irhs '^\\s*\`define\\s*\\b$VSEC_name\\b' /p/mapleridge/mapleridge/Logic/rel_logic/latest/units/mapleridge_top/src/*.def | head -1`;
            #if($GrepResult =~ m/\/\/\s*0[xX][0-9a-fA-F]+/){
            #    ($VSEC_name_Value) = $GrepResult =~ /\/\/\s*(0[xX][0-9a-fA-F]+)/;
            #}
            #elsif($GrepResult =~ m/\w+\d+'h\d+/){
            #    ($VSEC_name_Value) = $GrepResult =~ /\w+\d+'h(\d+)/;
            #    $VSEC_name_Value = "0x".$VSEC_name_Value;
            #}
            #elsif($GrepResult =~ m/\w+\d+'d\d+/){
            #    ($VSEC_name_Value) = $GrepResult =~ /\w+\d+'d(\d+)/;
            #    $VSEC_name_Value = sprintf("0x%X" , $VSEC_name_Value);
            #}
            #else{
            #    print"\n#####Define value is not configure correctly#####\n"; 
            #}
        }
        #$VSEC_name_Value = substr $VSEC_name_Value, 2;
        $VSEC_offset_array[$VSEC_IDX] = substr $VSEC_offset_array[$VSEC_IDX], 2;
        if($VSEC_name =~ m/0[xX][0-9a-fA-F]+/){
            $VSEC_name_Value = sprintf("0x%X", hex($VSEC_name_Value) + hex($VSEC_offset_array[$VSEC_IDX]));
        }
        else {
            $VSEC_name_Value = sprintf("0x%X", $VSEC_name_Value + hex($VSEC_offset_array[$VSEC_IDX]));
        }
        ##### debug print #####    
        if ($debug){
            print"VSEC_name: -", $VSEC_name, "-\n";
            print"GrepResult: -", $GrepResult, "-\n"; 
            print"VSEC_name_Value: -", $VSEC_name_Value, "-\n"; 
        }
        push(@VSEC_name_Value_array,$VSEC_name_Value);
        $VSEC_IDX++;
    }
    
################  printing while Duplicating by number of Repeates from DontDelete   ################
    ################  looping through repeat    ################
    for (my $NumOfRepeats_IDX = 0 ; $NumOfRepeats_IDX < $NumOfRepeats ; $NumOfRepeats_IDX++){
        my @DF_spl;
        my @temp_offset_value_spl;
        my @temp_offset_value_spl_duplicated;
        my $Row_IDX;
        my @TempDF;
        #print "BORIS1 - NumOfRepeats: $NumOfRepeats\n";
        #print "BORIS1 - NumOfRepeats_IDX: $NumOfRepeats_IDX\n";
        $ColumnsHOA{'VSEC_name(tar_index)[12:0]'} = ();
        $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0] = substr $VSEC_name_Value_array[$NumOfRepeats_IDX], 2;   
        my @temp_split2 =split "", $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0];
        while ($#temp_split2 <=3){  #Padding with zeros until got in total 4 numbers, atleast 1 is exsits and add up to another 3 or less.
            $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0]="0".$ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0];
            @temp_split2 =split "", $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0];
        }
        $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0]="0x".$ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0];
        $ColumnsHOA{'Sub-function'} = ();
        $ColumnsHOA{'Sub-function'}[0] = $SubFunction[$NumOfRepeats_IDX];
        $ColumnsHOA{'pcie_sw_regs_access[23:23]'} = ();
        $ColumnsHOA{'pcie_sw_regs_access[23:23]'}[0] = $pcie_sw_regs_access[$NumOfRepeats_IDX];
        $ColumnsHOA{'cio_sw_regs_access[22:22]'} = ();
        $ColumnsHOA{'cio_sw_regs_access[22:22]'}[0] = $cio_sw_regs_access[$NumOfRepeats_IDX];
        $ColumnsHOA{'tar_cs[20:19]'} = ();
        $ColumnsHOA{'tar_cs[20:19]'}[0] = $tar_cs[$NumOfRepeats_IDX];
        $ColumnsHOA{'tar_port[18:13]'} = ();
        $ColumnsHOA{'tar_port[18:13]'}[0] = substr $tar_port[$NumOfRepeats_IDX], 2;
        my @temp_split3 =split "", $ColumnsHOA{'tar_port[18:13]'}[0];
        while ($#temp_split3 <=1){#Padding with zeros until got in total 2 numbers, atleast 1 is exsits and add up to another 1 pr no need at all.
            $ColumnsHOA{'tar_port[18:13]'}[0]="0".$ColumnsHOA{'tar_port[18:13]'}[0];
            @temp_split3 =split "", $ColumnsHOA{'tar_port[18:13]'}[0];
        }
        $ColumnsHOA{'tar_port[18:13]'}[0]="0x".$ColumnsHOA{'tar_port[18:13]'}[0];
	#Start of Fix - Row_IDX will start form 0 and add this if condition to handle the case of starting new sub-function with index that is NOT 0.        
	    for($Row_IDX = 0 ; $Row_IDX < scalar (@{$ColumnsHOA{"Offset"}}) ;$Row_IDX++){
	        if ($Row_IDX > 0) {
                $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX] = sprintf("%X",  hex($ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0]) + hex($ColumnsHOA{'Offset'}[$Row_IDX]) - hex($ColumnsHOA{'Offset'}[0]));
            }
            else {
                $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX] = sprintf("%X",  hex($ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[0]) + hex($ColumnsHOA{'Offset'}[$Row_IDX]));
            }
	    #End of fix - Row_IDX will start form 0 and add this if condition to handle the case of starting new sub-function with index that is NOT 0. 
            my @temp_split =split "", $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX];
            while ($#temp_split<=3){
                $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX] ="0".$ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX];
                @temp_split =split "", $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX];
            }
            $ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX]="0x".$ColumnsHOA{'VSEC_name(tar_index)[12:0]'}[$Row_IDX];  
            $ColumnsHOA{'Sub-function'}[$Row_IDX] = $SubFunction[$NumOfRepeats_IDX];
            $ColumnsHOA{'pcie_sw_regs_access[23:23]'}[$Row_IDX] = $pcie_sw_regs_access[$NumOfRepeats_IDX];
            $ColumnsHOA{'cio_sw_regs_access[22:22]'}[$Row_IDX] = $cio_sw_regs_access[$NumOfRepeats_IDX];
            $ColumnsHOA{'tar_cs[20:19]'}[$Row_IDX] = $tar_cs[$NumOfRepeats_IDX];
            $ColumnsHOA{'tar_port[18:13]'}[$Row_IDX] = substr $tar_port[$NumOfRepeats_IDX], 2;
            my @temp_split4 =split "", $ColumnsHOA{'tar_port[18:13]'}[$Row_IDX];
            while ($#temp_split4<=1){
                $ColumnsHOA{'tar_port[18:13]'}[$Row_IDX] ="0".$ColumnsHOA{'tar_port[18:13]'}[$Row_IDX];
                @temp_split4 =split "", $ColumnsHOA{'tar_port[18:13]'}[$Row_IDX];
            }
            $ColumnsHOA{'tar_port[18:13]'}[$Row_IDX] ="0x".$ColumnsHOA{'tar_port[18:13]'}[$Row_IDX];

###TEST BORIS list of default values###
            #Remove the depandency on the default value variable format. 
            #my $DV_Name_Check = $ColumnsHOA{'Addrmap'}[$Row_IDX]."_".$ColumnsHOA{'Field Name'}[$Row_IDX]."_DF";    
            #if (($ColumnsHOA{'Default value'}[$Row_IDX] =~ m/^\[/) or (($ColumnsHOA{'Default value'}[$Row_IDX] !~ m/^0x/) and ($ColumnsHOA{'Default value'}[$Row_IDX] =~ m/$DV_Name_Check/) )){}

            if (($ColumnsHOA{'Default value'}[$Row_IDX] =~ m/^\[/) and ($ColumnsHOA{'Default value'}[$Row_IDX] !~ m/^0x/)){
                print "Default Value is A List\n" if $debug;
                print "Default Value is A List: $ColumnsHOA{'Default value'}[$Row_IDX]\n" if $debug;
                ###START### Parse Dont Delete to find the name of the group that associated to sub_function.
                my $DD_Group_Name;
                my $Groups_row;
                my $Both = 0;
                if ($IP) {
                    $worksheet = $workbook->worksheet("dont_delete_IP");
                }
                else {
                    $worksheet = $workbook->worksheet("dont_delete");
                }
                print "Parsing WorkSheet: " ,$worksheet->get_name() ,"\n" if $debug;
                ( $row_min, $row_max_1 ) = $worksheet->row_range();
                $row_max = $row_max_1;
                ################ get row max ############## 
                for my $row ( $row_min .. $row_max_1 ) {
                    my $cell_0 = $worksheet->get_cell( $row,0);
                    if((not $cell_0) or $cell_0->value() =~ /^$/){
                        $row_max = $row;
                        last;
                    }
                    print $row, $cell_0->value(),  "\n" if $debug;
                }
                ################  read columns according to title - first row  ################
                ( $col_min, $col_max ) = $worksheet->col_range();
                my $row = $row_min;
                my %columns_name_hash;
                for my $col ( $col_min .. $col_max ) {
                    my $cell = $worksheet->get_cell( $row, $col );
                    %columns_name_hash=( 
                    "Sub-function"=>\@SubFunction,
                    "pcie_sw_regs_access[23:23]"=>\@pcie_sw_regs_access,
                    "cio_sw_regs_access[22:22]"=>\@cio_sw_regs_access,
                    "tar_cs[20:19]"=>\@tar_cs,
                    "tar_port[18:13]"=>\@tar_port,
                    "VSEC_name(tar_index)[12:0]"=>\@VSEC_name_array,
                    "Offset_in_VSEC"=>\@VSEC_offset_array,
                    "Groups"=>\@Groups
                    );
        
                    foreach my $column_name (keys %columns_name_hash){
                        if($cell->value() eq $column_name){
                            print "Column name: $column_name\n" if $debug;
                            for my $sub_row ( $row_min+1 .. $row_max) {
                                $cell = $worksheet->get_cell( $sub_row, $col );
                                print "$sub_row, $col  ", $cell->value(), "\n" if $debug;
                                if(!($cell->value() =~ /^$/)){ 
                                    push(@{$columns_name_hash{$column_name}},$cell->value());
                                    if (($column_name eq "Sub-function") and ($cell->value() eq $ColumnsHOA{'Addrmap'}[$Row_IDX])){
                                        $Groups_row = $sub_row;
                                        print "Groups_row: $Groups_row\n" if $debug;
                                    }
                                }
                            }
                        }
                    }
                }
                
                ##### Read dont_delete spreadsheet to table. #####
                if ($IP) {
                    $worksheet = $workbook->worksheet("dont_delete_IP");
                }
                else {
                    $worksheet = $workbook->worksheet("dont_delete");
                }
                ($col_min, $col_max) = $worksheet->col_range();
                my @table_dd2 = [];    #empty table for dont del.
                print "ROW MAX DONT DEL2: $row_max\n" if $debug;
                for my $row (1 .. $row_max) {
                    my $col_table_dd2 = $col_min;
                    for my $col ($col_min .. $col_max) {
                        my $cell = $worksheet->get_cell($row, $col);
                        my $header = $worksheet->get_cell(0, $col);
                        if (!$cell){
                            #print "DD2 - IF NOT CELL: ROW, COL: $row , $col\n" if $debug;
                            $col_table_dd2++;
                            next;
                        }
                        #print "DD2 - IF CELL: ROW, COL, col_table_dd2, VALUE: $row , $col , $col_table_dd2 , ",$cell->value(),"\n" if $debug;
                        if (!($cell->value() =~ /^$/) and ($cell)) {
                            ${$table_dd2[$row]}[$col_table_dd2] = $cell->value();
                            #print "DD - table_dd, ROW , COL_DD, VALUE, $row, $col_table_dd2 , ${$table_dd2[$row]}[$col_table_dd2]\n" if $debug;
                        }
                        $col_table_dd2++;
                    }
                }
                $DD_Group_Name = ${$table_dd2[$Groups_row]}[8];
                #print "CHECK5: Group Name: $DD_Group_Name\n";
                ###END### Parse Dont Delete to find the name of the group that associated to sub_function.

                ###START### Parse SW_DB_info spreadsheet to identify in which case of lits we are: ports, base/offet, or both
                #Parse SW_DB_info spreadsheet to identify in which case of lits we are: ports, base/offet, or both 
                my $worksheet_SW_DB_info = $workbook->worksheet("SW_DB_info");
                print "Parsing WorkSheet: " ,$worksheet_SW_DB_info->get_name() ,"\n" if $debug;
                my ( $row_min, $row_max_1 ) = $worksheet_SW_DB_info->row_range();
                my $row_max = $row_max_1;
                print "row_min, row_max: ", $row_min, $row_max, "\n" if $debug;
                ################ get row max ############## 
                for my $SW_DB_info_row ( $row_min .. $row_max_1 ) {
                    my $cell_0 = $worksheet_SW_DB_info->get_cell( $SW_DB_info_row,0);
                    if((not $cell_0) or $cell_0->value() =~ /^$/){
                        $row_max = $SW_DB_info_row;
                        last;
                    }
                    print "SW_DB_info, row, value: ", $SW_DB_info_row, $cell_0->value(),  "\n" if $debug;
                }
                ################  read columns according to title - first row  ################
                ( $col_min, $col_max ) = $worksheet_SW_DB_info->col_range();
                my $SW_DB_info_row = $row_min+1;  # skip firt row HEADER of the table : "Hierachical View"
                for my $col ( $col_min .. $col_max ) {
                    my $cell = $worksheet_SW_DB_info->get_cell( $SW_DB_info_row, $col );
                    %columns_name_hash_SW_DB_info=( 
                    "Groups"=>\@Groups_SW_DB_info,
                    "Project"=>\@Project_SW_DB_info,
                    "pcie_sw_regs_access[23:23]"=>\@pcie_sw_regs_access_SW_DB_info,
                    "cio_sw_regs_access[22:22]"=>\@cio_sw_regs_access_SW_DB_info,
                    "tar_cs[20:19]"=>\@tar_cs_SW_DB_info,
                    "tar_port[18:13]"=>\@tar_port_SW_DB_info,
                    "VSEC_name(tar_index)[12:0]"=>\@VSEC_name_array_SW_DB_info,
                    "VSEC_Base"=>\@VSEC_Base_array_SW_DB_info,
                    "Offset_in_VSEC"=>\@VSEC_offset_array_SW_DB_info
                    );

                    foreach my $column_name (keys %columns_name_hash_SW_DB_info){
                        if($cell->value() eq $column_name){
                            print "Column name: $column_name\n" if $debug;
                            for my $sub_row ( $row_min+2 .. $row_max) { # skip firt row HEADER of the table : "Hierachical View" and the Headers ofthe columns"
                                $cell = $worksheet_SW_DB_info->get_cell( $sub_row, $col );
                                #print "SW_DB_info, sub_row, col, cell valaue :" ,$sub_row, $col , $cell->value(), "\n" if $debug;
                                if(!($cell->value() =~ /^$/)){
                                    #print "$col , $sub_row\n";
                                    #print $cell->value(),"\n";
                                    #my $cell_value = $cell->value();
                                    if(($column_name eq "tar_port[18:13]" or $column_name eq "Offset_in_VSEC") and ($cell->value() !~ /^\[/) and ($cell->value() !~ /^0x/)) {
                                        my $Var_name_Value = $VarsHash{$cell->value()};
                                        push(@{$columns_name_hash_SW_DB_info{$column_name}},$Var_name_Value);
                                    }
                                    else {
                                        push(@{$columns_name_hash_SW_DB_info{$column_name}},$cell->value());
                                    }
                                }
                            }
                        }
                    }
                }
                my $temp_offset_value_spl_len;
                for my $sub_row ( $row_min .. $row_max-2) {
                    #print "CHECK6: $columns_name_hash_SW_DB_info{'Groups'}[$sub_row]\n";
                    if ($IP) {
                        if ((($columns_name_hash_SW_DB_info{'Project'}[$sub_row] eq "IP") or ($columns_name_hash_SW_DB_info{'Project'}[$sub_row] eq "Both")) and ($columns_name_hash_SW_DB_info{'Groups'}[$sub_row] eq $DD_Group_Name) and ($columns_name_hash_SW_DB_info{'tar_port[18:13]'}[$sub_row] =~ m/^\[/) and (($columns_name_hash_SW_DB_info{'VSEC_Base'}[$sub_row] =~ m/^\[/) or ($columns_name_hash_SW_DB_info{'Offset_in_VSEC'}[$sub_row] =~ m/^\[/))) {
                            my $temp_offset_value_str = $columns_name_hash_SW_DB_info{'Offset_in_VSEC'}[$sub_row];
                            $temp_offset_value_str =~ s/\[//;
                            $temp_offset_value_str =~ s/\]//;
                            @temp_offset_value_spl = split(', ', $temp_offset_value_str);
                            $temp_offset_value_spl_len = scalar(@temp_offset_value_spl);
                            $Both = 1;
                            #print "BOTH!! - $Both\n";
                        }
                    }    
                    else {
                        if ((($columns_name_hash_SW_DB_info{'Project'}[$sub_row] eq "Discrete") or ($columns_name_hash_SW_DB_info{'Project'}[$sub_row] eq "Both")) and ($columns_name_hash_SW_DB_info{'Groups'}[$sub_row] eq $DD_Group_Name) and ($columns_name_hash_SW_DB_info{'tar_port[18:13]'}[$sub_row] =~ m/^\[/) and (($columns_name_hash_SW_DB_info{'VSEC_Base'}[$sub_row] =~ m/^\[/) or ($columns_name_hash_SW_DB_info{'Offset_in_VSEC'}[$sub_row] =~ m/^\[/))) {
                            my $temp_offset_value_str = $columns_name_hash_SW_DB_info{'Offset_in_VSEC'}[$sub_row];
                            $temp_offset_value_str =~ s/\[//;
                            $temp_offset_value_str =~ s/\]//;
                            @temp_offset_value_spl = split(', ', $temp_offset_value_str);
                            $temp_offset_value_spl_len = scalar(@temp_offset_value_spl);
                            $Both = 1;
                            #print "BOTH!! - $Both\n";
                        }
                    }    
                }
                my $DF_temp_list_str = $ColumnsHOA{'Default value'}[$Row_IDX];
                $DF_temp_list_str =~ s/\[//;
                $DF_temp_list_str =~ s/\]//;
                # using split() function
                #print "TEMP LIST STR: $DF_temp_list_str\n" if $debug;
                @DF_spl = split(', ', $DF_temp_list_str);
                my $DF_spl_len = scalar(@DF_spl);
                #print "DF SPLIT LENGTH: $DF_spl_len\n" if $debug;
                #Need to check in which case we are (ports, base/offet, or both )
                #Instead num of repeates, need num of offsets or ports or VSEC BASes
                #Than, need to $TempDF[$Row_IDX]=$spl[$NumOfOFFSET_IDX];
                #Than, if both ports and offset, need loop ports time and push to array same data index times.
                if ($Both) {
                    my $num_of_dupilaction = $NumOfRepeats/$temp_offset_value_spl_len;
                    #print "num_of_dupilaction = NumOfRepeats/temp_offset_value_spl_len $num_of_dupilaction = $NumOfRepeats/$temp_offset_value_spl_len\n";
                    if (($DF_spl_len == $temp_offset_value_spl_len) and ($DF_temp_list_str !~ m/\*/)) {
                        for (my $offset_len_idx = 0 ; $offset_len_idx < $num_of_dupilaction; $offset_len_idx++){
                            push @temp_offset_value_spl_duplicated, @temp_offset_value_spl;
                        }
                        $TempDF[$Row_IDX]=$temp_offset_value_spl_duplicated[$NumOfRepeats_IDX];
                    }
                    elsif ($DF_temp_list_str =~ m/\*/) {
                        pop @DF_spl;
                        
                        my @DF_spl_new;
                        my @DF_spl_orig = @DF_spl;
                        my $DF_spl_len_new = scalar(@DF_spl);
                        #print "SPLIT LENGTH AFTER POP: $DF_spl_len_new\n" if $debug;
                        for (my $offset_len_idx = 0 ; $offset_len_idx < $num_of_dupilaction; $offset_len_idx++){
                            push @DF_spl_new, @DF_spl_orig;
                            for (my $padding_idx = $DF_spl_len_new ; $padding_idx < $temp_offset_value_spl_len ; $padding_idx++){
                                push @DF_spl_new, $DF_spl[$DF_spl_len_new-1];
                                #print "BOTH pad: $DF_spl[$DF_spl_len_new-1]\n";
                            }
                            #if ($offset_len_idx < $num_of_dupilaction-1){
                            #    push @DF_spl, @DF_spl_orig;
                            #    print "BOTH orig pad: @DF_spl_orig\n";
                            #}
                        }
                        #print "NumOfRepeats_IDX: $NumOfRepeats_IDX\n";
                        #print "Row_IDX: $Row_IDX\n";
                        $TempDF[$Row_IDX]=$DF_spl_new[$NumOfRepeats_IDX];
                        #print "value in the repeat $NumOfRepeats_IDX", $DF_spl_new[$NumOfRepeats_IDX] ,"\n";
                    }
                    else {
                        print "\n\n### ERROR!!! ### ==> Num Of Reapets is not equal to default value list lenght.\n\n";
                        exit;
                    }
                }
                else {
                    if (($DF_spl_len == $NumOfRepeats) and ($DF_temp_list_str !~ m/\*/)) {
                        $TempDF[$Row_IDX]=$DF_spl[$NumOfRepeats_IDX];
                    }
                    elsif ($DF_temp_list_str =~ m/\*/) {
                        pop @DF_spl;
                        my @DF_spl_new;
                        my @DF_spl_orig = @DF_spl;
                        my $DF_spl_len_new = scalar(@DF_spl);
                        #print "SPLIT LENGTH AFTER POP: $DF_spl_len_new\n" if $debug;
                        push @DF_spl_new,@DF_spl_orig;
                        for (my $padding_idx = $DF_spl_len_new ; $padding_idx < $NumOfRepeats ; $padding_idx++){
                            push @DF_spl_new, $DF_spl[$DF_spl_len_new-1];
                            #print "Single pad: $DF_spl[$padding_idx-1]\n";
                        }
                        $TempDF[$Row_IDX]=$DF_spl_new[$NumOfRepeats_IDX];
                    }
                    else {
                        print "\n\n### ERROR!!! ### ==> Num Of Reapets is not equal to default value list lenght.\n\n";
                        exit;
                    }
                }
            }
            else {
                $TempDF[$Row_IDX]=$ColumnsHOA{'Default value'}[$Row_IDX];
            }    
        }
        
        #print "NumOfRepeats2_IDX: $NumOfRepeats_IDX\n";
        ################  printing to output part by part  ################
        my $col = 0;
        for(my $idx=0; $idx<=$#ColumnArray_all;$idx++){
            my $key = $ColumnArray_all[$idx];
            my $ColumnsHOA_ref = \@{ $ColumnsHOA{$key} };          
            $worksheet1->write_col( $row_counter, $col, $ColumnsHOA_ref, $cell_format1);
            $col++;
        }
        my $TempDF_ref = \@TempDF;
        $worksheet1->write_col( $row_counter, 17, $TempDF_ref, $cell_format1);
        #print "row_counter: ",$row_counter, "\n";
        $row_counter += $row_max_counter;   #adding offset to future printing 
        $row_counter -= ($RealRowStart+1);     #printing as row_counter by counting from RealRowStart
        #print "TempDF: ",@TempDF, "\n";
        #print "TempDF Size: ",$#TempDF, "\n";
        
    }
}
##### Delete the last row from Main Excel. #####
for(my $col_dd = 3;$col_dd < 9;$col_dd++){
    my @array_undef = (' ');
    my @array_undef_ref = \@array_undef;
    $worksheet1->write_row( $row_counter, $col_dd, @array_undef_ref, $cell_format1);
}
print "final row counter: $row_counter\n" if $debug;
#$worksheet1->autofilter( 0, 0, 0, 37 );
$workbook->close();
move("All_Regs.xlsx", "$LocalPath") or die "Couldn't move file All_Regs.xlsx";
###################################################################################
######################               Functions               ######################
###################################################################################

#################################### create_excel #################################
### Create structure of the main final XLSX file with Headers and all settings. ###
###################################################################################
sub create_excel{
    print "create_excel function working\n" if $debug;
    my $ExcelName = shift;
    # Create a new Excel workbook
    $workbook = Excel::Writer::XLSX->new("$ExcelName.xlsx");
    # Add a worksheet
    $worksheet1 = $workbook->add_worksheet("$ExcelName");

    $worksheet1->set_column('A:C',10);
    $worksheet1->set_column('D:F',30);
    $worksheet1->set_column('G:H',15);
    $worksheet1->set_column('I:I',30);
    $worksheet1->set_column('J:L',15);
    $worksheet1->set_column('M:N',35);
    $worksheet1->set_column('O:P',7);
    $worksheet1->set_column('Q:S',15);
    $worksheet1->set_column('T:T',35);
    $worksheet1->set_column('U:U',17);
    $worksheet1->set_column('V:W',35);
    $worksheet1->set_column('X:AN',20);
    $worksheet1->set_column('AO:AO',45);

    #  Add and define a format
    my $header_format1 = $workbook->add_format; # Yellow background
    my $header_format2 = $workbook->add_format; # Special Blue background
    my $header_format3 = $workbook->add_format; # Special Green background
    my $header_format4 = $workbook->add_format; # Special Orange background
    my $header_format5 = $workbook->add_format; # Red background
    my $cell_format1   = $workbook->add_format; # Alignment to left

    $header_format1->set_border( 1 );
    $header_format1->set_bg_color( 'yellow' );
    $header_format1->set_bold();
    $header_format1->set_align( 'bottom' );

    $header_format2->set_border( 1 );
    $header_format2->set_bg_color( '#00B0F0' );
    $header_format2->set_bold();
    $header_format2->set_align( 'bottom' );

    $header_format3->set_border( 1 );
    $header_format3->set_bg_color( '50' );
    $header_format3->set_bold();
    $header_format3->set_align( 'bottom' );

    $header_format4->set_border( 1 );
    $header_format4->set_bg_color( '52' );
    $header_format4->set_bold();
    $header_format4->set_align( 'bottom' );

    $header_format5->set_border( 1 );
    $header_format5->set_bg_color( 'red' );
    $header_format5->set_bold();
    $header_format5->set_align( 'bottom' );

    $cell_format1->set_align( 'left' );

    # Write a formatted and unformatted string, row and column notation.
    $worksheet1->write( 0, 0,  'Owner',                     $header_format1 );
    $worksheet1->write( 0, 1,  'Project',                   $header_format1 );
    $worksheet1->write( 0, 2,  'Domain',                    $header_format1 );
    $worksheet1->write( 0, 3,  'Sub-function',              $header_format1 );
    $worksheet1->write( 0, 4,  'pcie_sw_regs_access_23_23', $header_format1 );
    $worksheet1->write( 0, 5,  'cio_sw_regs_access_22_22',  $header_format1 );
    $worksheet1->write( 0, 6,  'tar_cs_20_19',              $header_format1 );
    $worksheet1->write( 0, 7,  'tar_port_18_13',            $header_format1 );
    $worksheet1->write( 0, 8,  'VSEC_name-tar_index_12_0',  $header_format1 );
    $worksheet1->write( 0, 9,  'Offset-HEX',                $header_format1 );
    $worksheet1->write( 0, 10, 'Index',                     $header_format1 );
    $worksheet1->write( 0, 11, 'Checker1',                  $header_format2 );
    $worksheet1->write( 0, 12, 'Register Name',             $header_format1 );
    $worksheet1->write( 0, 13, 'RTL Name',                  $header_format1 );
    $worksheet1->write( 0, 14, 'MSB',                       $header_format1 );
    $worksheet1->write( 0, 15, 'LSB',                       $header_format1 );
    $worksheet1->write( 0, 16, 'Checker2',                  $header_format2 );
    $worksheet1->write( 0, 17, 'Default value',             $header_format1 );
    $worksheet1->write( 0, 18, 'Attribute',                 $header_format1 );
    $worksheet1->write( 0, 19, 'Field Name',                $header_format1 );
    $worksheet1->write( 0, 20, 'Security Level',            $header_format1 );
    $worksheet1->write( 0, 21, 'Power domain',              $header_format1 );
    $worksheet1->write( 0, 22, 'Module Name',               $header_format1 );
    $worksheet1->write( 0, 23, 'CDC Stable',                $header_format1 );
    $worksheet1->write( 0, 24, 'Not HW reg',                $header_format3 );
    $worksheet1->write( 0, 25, 'DRAM addr',                 $header_format3 );
    $worksheet1->write( 0, 26, 'Space Size',                $header_format3 );
    $worksheet1->write( 0, 27, 'test_signal_name',          $header_format3 );
    $worksheet1->write( 0, 28, 'IntelRsvd',                 $header_format3 );
    $worksheet1->write( 0, 29, 'Register Path',             $header_format3 );
    $worksheet1->write( 0, 30, 'space',                     $header_format3 );
    $worksheet1->write( 0, 31, 'baseaddress',               $header_format3 );
    $worksheet1->write( 0, 32, 'Name Description',          $header_format3 );
    $worksheet1->write( 0, 33, 'reg name for pdf',          $header_format3 );
    $worksheet1->write( 0, 34, 'field name for pdf',        $header_format3 );
    $worksheet1->write( 0, 35, 'instance',                  $header_format3 );
    $worksheet1->write( 0, 36, 'S&R_Group',                 $header_format3 );
    $worksheet1->write( 0, 37, 'Absolute offs',             $header_format3 );
    $worksheet1->write( 0, 38, 'S&R_Order',                 $header_format3 );
    $worksheet1->write( 0, 39, 'signal_name',               $header_format4 );
    $worksheet1->write( 0, 40, 'Full Field Description',    $header_format1 );
    $worksheet1->freeze_panes( 1, 0 );    # Freeze the first row
    $worksheet1->autofilter( 0, 0, 0, 40 );
    print "create_excel function finished working\n" if $debug;
}

#################################### create_excel_local #################################
### Create structure of the local temporary XLSX files with Headers and all settings. ###
#########################################################################################
sub create_excel_local{
    print "create_excel_local function working\n" if $debug;
    my $ExcelName = shift;

    # Create a new Excel workbook
    $workbook = Excel::Writer::XLSX->new("$ExcelName.xlsx");
    # Add a worksheet
    $worksheet1 = $workbook->add_worksheet("$ExcelName");
    if ($IP) {
        $worksheet2 = $workbook->add_worksheet('dont_delete_IP');
    }
    else {
        $worksheet2 = $workbook->add_worksheet('dont_delete');
    }
    $worksheet3 = $workbook->add_worksheet('SW_DB_info');
    


    $worksheet1->set_column('A:C',8);
    $worksheet1->set_column('D:D',25);
    $worksheet1->set_column('E:H',10);
    $worksheet1->set_column('I:J',25);
    $worksheet1->set_column('K:L',7);
    $worksheet1->set_column('M:O',13);
    $worksheet1->set_column('P:S',25);
    $worksheet1->set_column('T:AJ',20);
    $worksheet1->set_column('AK:AK',35);

    # Tab Worksheet - red color
    $worksheet2->set_tab_color( 'red' );
    $worksheet2->set_column('A:C',25);
    $worksheet2->set_column('D:E',15);
    $worksheet2->set_column('F:F',30);
    $worksheet2->set_column('G:H',15);
    $worksheet2->set_column('I:I',25);
    $worksheet2->set_column('J:K',15);
    $worksheet2->set_column('L:L',20);
    $worksheet2->set_column('M:M',10);
    $worksheet2->set_column('N:N',35);
    $worksheet2->set_column('O:O',10);
    $worksheet2->set_column('P:S',20);


    #SW_DB_info
    $worksheet3->set_column('A:A',25);
    $worksheet3->set_column('B:B',15);
    $worksheet3->set_column('C:D',30);
    $worksheet3->set_column('E:F',15);
    $worksheet3->set_column('G:G',30);
    $worksheet3->set_column('H:H',15);
    $worksheet3->set_column('I:I',20);
    $worksheet3->set_column('J:M',40);

    #  Add and define a format
    my $header_format1 = $workbook->add_format; # Yellow background
    my $header_format2 = $workbook->add_format; # Special Blue background
    my $header_format3 = $workbook->add_format; # Special Green background
    my $header_format4 = $workbook->add_format; # Special Orange background
    my $header_format5 = $workbook->add_format; # Red background
    my $header_format6 = $workbook->add_format; # SW_DB_info Main HEADER
    my $cell_format1   = $workbook->add_format; # Alignment to left

    $header_format1->set_border( 1 );
    $header_format1->set_bg_color( 'yellow' );
    $header_format1->set_bold();
    $header_format1->set_align( 'bottom' );

    $header_format2->set_border( 1 );
    $header_format2->set_bg_color( '#00B0F0' );
    $header_format2->set_bold();
    $header_format2->set_align( 'bottom' );

    $header_format3->set_border( 1 );
    $header_format3->set_bg_color( '50' );
    $header_format3->set_bold();
    $header_format3->set_align( 'bottom' );

    $header_format4->set_border( 1 );
    $header_format4->set_bg_color( '52' );
    $header_format4->set_bold();
    $header_format4->set_align( 'bottom' );

    $header_format5->set_border( 1 );
    $header_format5->set_bg_color( 'red' );
    $header_format5->set_bold();
    $header_format5->set_align( 'bottom' );
    
    $header_format6->set_border( 1 );
    $header_format6->set_bold();
    $header_format6->set_align( 'center' );

    $cell_format1->set_align( 'left' );

    # Write a formatted and unformatted string, row and column notation.
    $worksheet1->write( 0, 0,  'Owner',                  $header_format1 );
    $worksheet1->write( 0, 1,  'Project',                $header_format1 );
    $worksheet1->write( 0, 2,  'Domain',                 $header_format1 );
    $worksheet1->write( 0, 3,  'Addrmap',                $header_format1 );
    $worksheet1->write( 0, 4,  'Base addr',              $header_format1 );
    $worksheet1->write( 0, 5,  'Offset',                 $header_format1 );
    $worksheet1->write( 0, 6,  'index',                  $header_format1 );
    $worksheet1->write( 0, 7,  'Checker1',               $header_format2 );
    $worksheet1->write( 0, 8,  'Register Name',          $header_format1 );
    $worksheet1->write( 0, 9,  'RTL Name',               $header_format1 );
    $worksheet1->write( 0, 10, 'MSB',                    $header_format1 );
    $worksheet1->write( 0, 11, 'LSB',                    $header_format1 );
    $worksheet1->write( 0, 12, 'Checker2',               $header_format2 );
    $worksheet1->write( 0, 13, 'Default value',          $header_format1 );
    $worksheet1->write( 0, 14, 'Attribute',              $header_format1 );
    $worksheet1->write( 0, 15, 'Field Name',             $header_format1 );
    $worksheet1->write( 0, 16, 'Security Level',         $header_format1 );
    $worksheet1->write( 0, 17, 'Power domain',           $header_format1 );
    $worksheet1->write( 0, 18, 'Module Name',            $header_format1 );
    $worksheet1->write( 0, 19, 'CDC Stable',             $header_format1 );
    $worksheet1->write( 0, 20, 'Not HW reg',             $header_format3 );
    $worksheet1->write( 0, 21, 'DRAM addr',              $header_format3 );
    $worksheet1->write( 0, 22, 'Space Size',             $header_format3 );
    $worksheet1->write( 0, 23, 'test_signal_name',       $header_format3 );
    $worksheet1->write( 0, 24, 'IntelRsvd',              $header_format3 );
    $worksheet1->write( 0, 25, 'Register Path',          $header_format3 );
    $worksheet1->write( 0, 26, 'space',                  $header_format3 );
    $worksheet1->write( 0, 27, 'baseaddress',            $header_format3 );
    $worksheet1->write( 0, 28, 'Name Description',       $header_format3 );
    $worksheet1->write( 0, 29, 'reg name for pdf',       $header_format3 );
    $worksheet1->write( 0, 30, 'field name for pdf',     $header_format3 );
    $worksheet1->write( 0, 31, 'instance',               $header_format3 );
    $worksheet1->write( 0, 32, 'S&R_Group',              $header_format3 );
    $worksheet1->write( 0, 33, 'Absolute offs',          $header_format3 );
    $worksheet1->write( 0, 34, 'S&R_Order',              $header_format3 );
    $worksheet1->write( 0, 35, 'signal_name',            $header_format4 );
    $worksheet1->write( 0, 36, 'Full Field Description', $header_format1 );

    $worksheet2->write( 0, 0,  'Sub-function',               $header_format1 );
    $worksheet2->write( 0, 1,  'pcie_sw_regs_access[23:23]', $header_format1 );
    $worksheet2->write( 0, 2,  'cio_sw_regs_access[22:22]',  $header_format1 );
    $worksheet2->write( 0, 3,  'tar_cs[20:19]',              $header_format1 );
    $worksheet2->write( 0, 4,  'tar_port[18:13]',            $header_format1 );
    $worksheet2->write( 0, 5,  'VSEC_name(tar_index)[12:0]', $header_format1 );
    $worksheet2->write( 0, 6,  'VSEC_Base',                  $header_format1 );
    $worksheet2->write( 0, 7,  'Offset_in_VSEC',             $header_format1 );
    $worksheet2->write( 0, 8,  'Groups',                     $header_format1 );
    $worksheet2->write( 0, 9,  'Function',                   $header_format1 );
    $worksheet2->write( 0, 10, 'Attribute',                  $header_format5 );
    $worksheet2->write( 0, 11, 'Security Level',             $header_format5 );
    $worksheet2->write( 0, 12, 'HW/MEM',                     $header_format5 );
    $worksheet2->write( 0, 13, 'Power domain',               $header_format5 );
    $worksheet2->write( 0, 14, 'Project',                    $header_format5 );
    $worksheet2->write( 0, 15, 'CDC Stable',                 $header_format5 );
    $worksheet2->write( 0, 16, 'calc_VSEC_Base',             $header_format3 );
    $worksheet2->write( 0, 17, 'calc_Offset_in_VSEC',        $header_format3 );
    $worksheet2->write( 0, 18, 'Total(DEC)',                 $header_format3 );

    $worksheet3->write( 0, 0,  'Hierarchical View',                               $header_format6 );
    $worksheet3->write( 1, 0,  'Groups',                                                 $header_format1 );
    $worksheet3->write( 1, 1,  'Project',                                                $header_format1 );
    $worksheet3->write( 1, 2,  'pcie_sw_regs_access[23:23]',                             $header_format1 );
    $worksheet3->write( 1, 3,  'cio_sw_regs_access[22:22]',                              $header_format1 );
    $worksheet3->write( 1, 4,  'tar_cs[20:19]',                                          $header_format1 );
    $worksheet3->write( 1, 5,  'tar_port[18:13]',                                        $header_format1 );
    $worksheet3->write( 1, 6,  'VSEC_name(tar_index)[12:0]',                             $header_format1 );
    $worksheet3->write( 1, 7,  'VSEC_Base',                                              $header_format1 );
    $worksheet3->write( 1, 8,  'Offset_in_VSEC',                                         $header_format1 );
    $worksheet3->write( 1, 9,  'Selector first_level_hirearchy',                         $header_format1 );
    $worksheet3->write( 1, 10,  'Selector second_level_hirearchy',                        $header_format1 );
    $worksheet3->write( 1, 11,  'Selector third_level_hirearchy',                         $header_format1 );
    $worksheet3->write( 1, 12,  'Valid second_hierarchy_index per first_level_hirearchy', $header_format1 );


    $worksheet1->freeze_panes( 1, 0 );    # Freeze the first row
    print "create_excel_local function finished working\n" if $debug;
}

#################################### split_excels ###################################################
### Split all neccessary excels files into small excels that will be unique with own dont_delete. ###
#####################################################################################################
sub split_excels {
    my $CloseFlag = 0;
    my $row_max;
    my @fileList = @_;
    chomp(@fileList);
    my @copyList;
    my $TruncFileName;
    print "split_excels function working\n" if $debug;
    foreach my $RegsXLSX (@fileList) {
        ####################    Parsing Excel File  ################
        print "\n", "Parsing Excel File: ", $RegsXLSX, "\n";
        my $parser = Spreadsheet::ParseXLSX->new;
        my $workbook = $parser->parse("$RegsXLSX");
        if (!defined $workbook) {
            die $parser->error(), ".\n";
        }
        ####################    Parsing don't_delete spreadsheet  ################
        my $worksheet;
        if ($IP) {
            $worksheet = $workbook->worksheet("dont_delete_IP");
        }
        else {
            $worksheet = $workbook->worksheet("dont_delete");
        }
        print "Parsing WorkSheet: ", $worksheet->get_name(), "\n";
        my ($row_min, $row_max_1) = $worksheet->row_range();
        $row_max = $row_max_1;
        ##################### get row max ###########################
        for my $row ($row_min .. $row_max_1) {
            my $cell_0 = $worksheet->get_cell($row, 0);
            if ((not $cell_0) or $cell_0->value() =~ /^$/) {
                $row_max = $row;
                last;
            }
            print $row, $cell_0->value(), "\n" if $debug;
        }
        my $row_max_dont_del = $row_max;
        ################  read columns according to title - first row  ################
        my @SubFunction;
        my @pcie_sw_regs_access;
        my @cio_sw_regs_access;
        my @tar_cs;
        my @tar_port;
        my @VSEC_name_array;
        my $NumOfRepeats;
        my ($col_min, $col_max) = $worksheet->col_range();
        my $row = $row_min;
        for my $col ($col_min .. $col_max) {
            my $cell = $worksheet->get_cell($row, $col);
            my %columns_name_hash = (
                "Sub-function"                => \@SubFunction,
                "pcie_sw_regs_access[23:23]"  => \@pcie_sw_regs_access,
                "cio_sw_regs_access[22:22]"   => \@cio_sw_regs_access,
                "tar_cs[20:19]"               => \@tar_cs,
                "tar_port[18:13]"             => \@tar_port,
                "VSEC_name(tar_index)[12:0]"  => \@VSEC_name_array
            );

            foreach my $column_name (keys %columns_name_hash) {
                if ($cell->value() eq $column_name) {
                    print "Column name: $column_name\n" if $debug;
                    for my $sub_row ($row_min + 1 .. $row_max) {
                        $cell = $worksheet->get_cell($sub_row, $col);
                        print "$sub_row, $col  ", $cell->value(), "\n" if $debug;
                        if (!($cell->value() =~ /^$/)) {
                            push(@{$columns_name_hash{$column_name}}, $cell->value());
                        }
                    }
                }
            }
        }
        ################    Parsing Excel sheet  ################
        $worksheet = $workbook->worksheet(0);
        print "Parsing WorkSheet: ", $worksheet->get_name(), "\n";
        ($row_min, $row_max_1) = $worksheet->row_range();
        print "row_min , row_max_1: $row_min, $row_max_1\n" if $debug;
        my $row_max = $row_max_1;
        ################ get row max and RealRowStart. ###############
        my $StartFlag = 0;
        my @Addrmap;
        for my $row ($row_min .. $row_max_1 + 1) {
            my $cell_0 = $worksheet->get_cell($row, 0);
            if (!$StartFlag) {
                next unless $cell_0;
            }
            if (not $StartFlag and $cell_0->value() =~ /Owner/) {
                $RealRowStart = $row;
                $StartFlag = 1;
                print "RealRowStart: $RealRowStart\n" if $debug;
            }
            if (((not $cell_0) or $cell_0->value() =~ /^$/) and $StartFlag) {
                $row_max = $row - 1;
                last;
            }
        }
        print "Row Max $row_max\n" if $debug;
        ($col_min, $col_max) = $worksheet->col_range();
        for my $col ($col_min .. $col_max) {
            my $cell = $worksheet->get_cell($RealRowStart, $col);
            if ($cell) {
                next unless $cell->value() =~ "Addrmap";
            }
            print "\nrow,col: $RealRowStart , $col \n" if $debug;
            for my $row ($RealRowStart + 1 .. $row_max) {
                $cell = $worksheet->get_cell($row, $col);
                if (!($cell->value() =~ /^$/)) {
                    print "row,col: $row , $col", "###", $cell->value(), "\n" if $debug;
                    push @Addrmap, $cell->value();
                }
            }
            last;
        }           
        ######### End of parsing dont del and table from excel file #######
        if ($debug){
            print "Addrmap array:", @Addrmap;
            print "\n\n";
            print "Subfunction array:", @SubFunction;
            print "\n";
        }
        my @UniqArray;
        my $NumofSubfunction;
        @UniqArray = uniq @Addrmap;
        print "NumofAddrmap:", scalar @UniqArray, "\n" if $debug;
        print "HELLO\n" if $debug;
        @UniqArray = uniq @SubFunction;
        print "NumofSubfunction:", scalar @UniqArray, "\n" if $debug;
        my @table;
        my $splitFlag = 0;
        @UniqArray = uniq @Addrmap;


        print "=@UniqArray=\n" if $debug;
        ##### Split main excel and dont_delete #####
        ##### Read main excel to table. #####
        ($col_min, $col_max) = $worksheet->col_range();
        for my $row ($RealRowStart + 1 .. $row_max) {
            my $col_table = $col_min;
            for my $col ($col_min .. $col_max) {
                my $cell = $worksheet->get_cell($row, $col);
                if (!$cell){                
                    $col_table++;
                    next;
                }
                #next unless $cell;
                if (!($cell->value() =~ /^$/) and ($cell)) {
                    ${$table[$row]}[$col_table] = $cell->value();
                }
                $col_table++;
            }
        }
        

        $worksheet = $workbook->worksheet("SW_DB_info");
        my ($row_min_sw_db_info, $row_max_sw_db_info) = $worksheet->row_range();
        my ($col_min_sw_db_info, $col_max_sw_db_info) = $worksheet->col_range();
        my @table_sw_db_info = [];    #empty table for dont del.
        for my $row (2 .. $row_max_sw_db_info) {
            for my $col ($col_min_sw_db_info .. $col_max_sw_db_info) {
                my $cell = $worksheet->get_cell($row, $col);
                if (!($cell->value() =~ /^$/) and ($cell)) {
                    ${$table_sw_db_info[$row]}[$col] = $cell->value();
                }
            }
        }

        for (my $rowIdx = 0; $rowIdx < scalar @table_sw_db_info; $rowIdx++) {
            my @row = @{$table_sw_db_info[$rowIdx]};
            my $rowRef = \@row;
            $worksheet3->write_row($rowIdx+2, 0, $rowRef, $cell_format1);
        }


        if ($IP) {
            $worksheet = $workbook->worksheet("dont_delete_IP");
        }
        else {
            $worksheet = $workbook->worksheet("dont_delete");
        }
        ($col_min, $col_max) = $worksheet->col_range();
        my @table_dd = [];    #empty table for dont del.
        for my $row (1 .. $row_max_dont_del) {
            my $col_table_dd = $col_min;
            for my $col ($col_min .. $col_max) {
                my $cell = $worksheet->get_cell($row, $col);
                if (!$cell){                
                    $col_table_dd++;
                    next;
                }
                if (!($cell->value() =~ /^$/) and ($cell)) {
                    ${$table_dd[$row]}[$col_table_dd] = $cell->value();
                }
                $col_table_dd++;
            }
        }
        
        for (my $i = 0; $i < scalar @UniqArray; $i++) {
            print "-$UniqArray[$i]-\n" if $debug;
            $TruncFileName = substr($UniqArray[$i], 0, 30);
            create_excel_local("$TruncFileName"); #create new excel file with header
            my $AddrmapIndex = 3;
            my $rowIdx_real = 0;
            for (my $rowIdx = 0; $rowIdx < scalar @table; $rowIdx++) {
                next unless $table[$rowIdx];
                my @row = @{$table[$rowIdx]};
                unless ($UniqArray[$i] eq $row[$AddrmapIndex]) {
                    next;
                }
                my $rowRef = \@row;
                $worksheet1->write_row($rowIdx_real + 1, 0, $rowRef, $cell_format1);
                $rowIdx_real++;
            }
            #split also dontdel.
            #read dontdel table.
            $rowIdx_real=0;
            for (my $rowIdx = 0;$rowIdx< scalar @table_dd ; $rowIdx++){
                next unless $table_dd[$rowIdx];#empty line
                my @row = @{$table_dd[$rowIdx]};
                next unless $row[0];
                unless ($UniqArray[$i] eq $row[8]){
                    next;
                }
                #splice(@row,6,1);
                my $rowRef = \@row;
                $worksheet2->write_row($rowIdx_real + 1, 0, $rowRef, $cell_format1);
                $rowIdx_real++;
            }
            if ($debug){
                my $str = `ls -l $UniqArray[$i].xlsx`;
                foreach my $x (1..10){
                    print "==========================\n";
                }
                print "$str\n";
            }
            push @copyList,"$UniqArray[$i]";
        }                
        #loop over excels files.
    ##### Copy all splited excel files to local path. ##### 
    }
    $workbook->close();
    foreach my $file (@copyList){
        print "file move to local: ${file}_regs.xlsx\n";
        $TruncFileName = substr($file, 0, 30);
        move("$TruncFileName.xlsx", "$LocalPath") or die "Couldn't move file $file, $!";
    }
    print "split_excels function finished working\n" if $debug;   
}
######################################################### split_spreadsheets #############################################################
### Split all neccessary spreadsheets from multiple spreadsheet excel files into excel files that will be unique with own dont_delete. ###
##########################################################################################################################################
sub SplitSpreadSheets{
    my @fileList = @_;
    chomp(@fileList);
    my $row_max;
    my @CopyList;
    my $TruncFileName;
    my $worksheet_count;
    my $CloseFlag = 0;
    my $index;
    my $DDsheetIDX;
    my @fileListSpliced = @fileList;
    print "SplitSpreadSheets function working\n";
    foreach my $RegsXLSX (@fileList) {
        my $parser = Spreadsheet::ParseXLSX->new;
        my $workbook = $parser->parse("$RegsXLSX");
        if (!defined $workbook) {
            die $parser->error(), ".\n";
        }
        print "Excel File: " ,$RegsXLSX, "\n";
        #next;
        $worksheet_count = $workbook->worksheet_count();
        print "worksheet count: " ,$worksheet_count, "\n";
        if (($worksheet_count > 3 and $IP) or ($worksheet_count > 2 and not $IP) ){
            $CloseFlag = 1;
            ####################    Parsing don't_delete spreadsheet  ################
            my $worksheet;
            if ($IP) {
                $worksheet = $workbook->worksheet("dont_delete_IP");
            }
            else {
                $worksheet = $workbook->worksheet("dont_delete");
            }
            print "Parsing WorkSheet: ", $worksheet->get_name(), "\n";
            my ($row_min, $row_max_1) = $worksheet->row_range();
            $row_max = $row_max_1;
            ##################### get row max ###########################
            for my $row ($row_min .. $row_max_1) {
                my $cell_0 = $worksheet->get_cell($row, 0);
                if ((not $cell_0) or $cell_0->value() =~ /^$/) {
                    $row_max = $row;
                    last;
                }
                print $row, $cell_0->value(), "\n" if $debug;
            }
            my $row_max_dont_del = $row_max;
            ################  read columns according to title - first row  ################
            my @SubFunction;
            my @pcie_sw_regs_access;            
            my @cio_sw_regs_access;
            my @tar_cs;
            my @tar_port;
            my @VSEC_name_array;
            my $NumOfRepeats;
            my ($col_min, $col_max) = $worksheet->col_range();
            my $row = $row_min;
            print "COL_MIN:COL_MAX: $col_min:$col_max\n" if $debug;
            for my $col ($col_min .. $col_max) {
                print "Row:Col: $row:$col\n" if $debug;
                my $cell = $worksheet->get_cell($row, $col);
                my %columns_name_hash = (
                "Sub-function"                => \@SubFunction,
                "pcie_sw_regs_access[23:23]"  => \@pcie_sw_regs_access,
                "cio_sw_regs_access[22:22]"   => \@cio_sw_regs_access,
                "tar_cs[20:19]"               => \@tar_cs,
                "tar_port[18:13]"             => \@tar_port,
                "VSEC_name(tar_index)[12:0]"  => \@VSEC_name_array
                );
                foreach my $column_name (keys %columns_name_hash) {
                    if ($cell->value() eq $column_name) {
                        print "Column name: $column_name\n" if $debug;
                        for my $sub_row ($row_min + 1 .. $row_max) {
                            $cell = $worksheet->get_cell($sub_row, $col);
                            print "$sub_row, $col  ", $cell->value(), "\n" if $debug;
                            if (!($cell->value() =~ /^$/)) {
                                push(@{$columns_name_hash{$column_name}}, $cell->value());
                            }
                        }
                    }
                }
            }
            my @Groups;
            ($col_min, $col_max) = $worksheet->col_range();
            for my $col ($col_min .. $col_max) {
                my $cell = $worksheet->get_cell($row_min, $col);
                if ($cell) {
                    next unless $cell->value() =~ "Groups";
                }
                print "\nrow,col: $row_min , $col \n" if $debug;
                for my $row ($row_min + 1 .. $row_max_dont_del) {
                    $cell = $worksheet->get_cell($row, $col);
                    if (!($cell->value() =~ /^$/)) {
                        print "row,col: $row , $col", "###", $cell->value(), "\n" if $debug;
                        push @Groups, $cell->value();
                    }
                }
                last;
            }
            ################    Find the relevant spreadsheets  ################
            my $worksheet_count = $workbook->worksheet_count();
            print "number of Original worksheets is: $worksheet_count\n";
            for (my $worksheet_idx = 0; $worksheet_idx < $worksheet_count; $worksheet_idx++){
                my $worksheet = $workbook->worksheet($worksheet_idx);
                my $worksheetName = $worksheet->get_name();
                if ($worksheetName eq "dont_delete") {
                    $DDsheetIDX = $worksheet_idx;
                }
            }
            ################    Loop on relevant spreadsheets  ################
            print "number of Relevant worksheets is: $DDsheetIDX\n";
            for (my $worksheet_idx = 0; $worksheet_idx < $DDsheetIDX; $worksheet_idx++){
            ################    Parsing Excel sheet  ################
                my $worksheet = $workbook->worksheet($worksheet_idx);
                my $worksheetName = $worksheet->get_name();   
                print "Parsing WorkSheet: ", $worksheetName, "\n";
                my ($row_min, $row_max_1) = $worksheet->row_range();
                print "row_min , row_max_1: $row_min, $row_max_1\n" if $debug;
                my $row_max = $row_max_1;
                ################ get row max and RealRowStart. ###############
                my $StartFlag = 0;
                for my $row ($row_min .. $row_max_1 + 1) {
                    my $cell_0 = $worksheet->get_cell($row, 0);
                    if (!$StartFlag) {
                        next unless $cell_0;
                    }
                    if (not $StartFlag and $cell_0->value() =~ /Owner/) {
                        $RealRowStart = $row;
                        $StartFlag = 1;
                        print "RealRowStart: $RealRowStart\n" if $debug;
                    }
                    if (((not $cell_0) or $cell_0->value() =~ /^$/) and $StartFlag) {
                        $row_max = $row - 1;
                        print "row_max: $row_max\n" if $debug;
                        last;
                    }
                }
                ##### Read spreadsheet to table. #####
                my @table;
                my ($col_min, $col_max) = $worksheet->col_range();
                my @AddressmapArray;
                for my $row ($RealRowStart + 1 .. $row_max) {
                    my $project_cell = $worksheet->get_cell($row, 1);
                    if ($IP and ($project_cell->value() eq "Discrete")) {
                        next;
                    }
                    elsif (not $IP and ($project_cell->value() eq "IP")) {
                        next;
                    }
                    my $col_table = $col_min;
                    for my $col ($col_min .. $col_max) {
                        my $cell_header = $worksheet->get_cell($RealRowStart, $col);
                        #print "cell_header of ROW, COL: $RealRowStart , $col\n" if $debug;
                        if (!($cell_header->value() ~~ @ColumnArray)) {
                            next;
                        }
                        
                        my $cell = $worksheet->get_cell($row, $col);
                        if (!$cell){
                            #print "IF NOT CELL: ROW, COL: $row , $col\n" if $debug;
                            $col_table++;
                            next;
                        }
                        #next unless $cell;
                        if (!($cell->value() =~ /^$/) and ($cell)) {
                             
                            ${$table[$row]}[$col_table] = $cell->value();
                            if ($cell_header->value() eq "Addrmap"){
                                push @AddressmapArray , $cell->value();
                            }    
                        }
                        $col_table++;
                    }
                }
                                ##### Read SW_DB_info spreadsheet to table. #####
                my $worksheet_SW_DB_info = $workbook->worksheet("SW_DB_info");
                my $worksheetName_SW_DB_info = $worksheet_SW_DB_info->get_name();   
                #print "check10 Parsing WorkSheet: ", $worksheetName_SW_DB_info, "\n";
                my ($row_min_SW_DB_info, $row_max_1_SW_DB_info) = $worksheet_SW_DB_info->row_range();
                print "row_min_SW_DB_info , row_max_1_SW_DB_info: $row_min_SW_DB_info, $row_max_1_SW_DB_info\n" if $debug;
                my $row_max_SW_DB_info = $row_max_1_SW_DB_info;

                my $StartFlag_SW_DB_info = 0;
                for my $row ($row_min_SW_DB_info .. $row_max_1_SW_DB_info + 1) {
                    #print "row check Boris - SW_DB_info", $row, "\n";
                    my $cell_0 = $worksheet_SW_DB_info->get_cell($row, 0);
                    if (!$StartFlag_SW_DB_info) {
                        next unless $cell_0;
                        #print "CHECK\n";
                    }
                    if (not $StartFlag_SW_DB_info and $cell_0->value() =~ /Groups/) {
                        $RealRowStart = $row;
                        $StartFlag_SW_DB_info = 1;
                        print "RealRowStart: $RealRowStart\n" if $debug;
                    }
                    if (((not $cell_0) or $cell_0->value() =~ /^$/) and $StartFlag_SW_DB_info) {
                        $row_max_SW_DB_info = $row - 1;
                        print "row_max_SW_DB_info: $row_max_SW_DB_info\n" if $debug;
                        last;
                    }
                }
                my @table_SW_DB_info = [];
                my ($col_min_SW_DB_info, $col_max_SW_DB_info) = $worksheet_SW_DB_info->col_range();
                for my $row_SW_DB_info (2 .. $row_max_SW_DB_info) {
                    my $col_table_SW_DB_info = $col_min_SW_DB_info;
                    for my $col_SW_DB_info ($col_min_SW_DB_info .. $col_max_SW_DB_info) {
                        #print "CHECK2 row_SW_DB_info, col_SW_DB_info: ,$row_SW_DB_info, $col_SW_DB_info", "\n";
                        my $cell = $worksheet_SW_DB_info->get_cell($row_SW_DB_info, $col_SW_DB_info);
                        if (!$cell){
                            print "IF NOT CELL: ROW, COL: $row_SW_DB_info , $col_SW_DB_info\n" if $debug;
                            $col_table_SW_DB_info++;
                            next;
                        }
                        #next unless $cell;
                        if (!($cell->value() =~ /^$/) and ($cell)) {
                            #print "CHECK3: row_SW_DB_info, col_table_SW_DB_info, value: --> " , "$row_SW_DB_info, $col_table_SW_DB_info,", $cell->value(), "\n";
                            ${$table_SW_DB_info[$row_SW_DB_info]}[$col_table_SW_DB_info] = $cell->value();    
                        }
                        $col_table_SW_DB_info++;
                    }
                } 


                ##### Read dont_delete spreadsheet to table. #####
                if ($IP) {
                    $worksheet = $workbook->worksheet("dont_delete_IP");
                }
                else {
                    $worksheet = $workbook->worksheet("dont_delete");
                }
                ($col_min, $col_max) = $worksheet->col_range();
                my @table_dd = [];    #empty table for dont del.
                print "ROW MAX DONT DEL: $row_max_dont_del\n" if $debug;
                for my $row (1 .. $row_max_dont_del) {
                    my $col_table_dd = $col_min;
                    for my $col ($col_min .. $col_max) {
                        my $cell = $worksheet->get_cell($row, $col);
                        my $header = $worksheet->get_cell(0, $col);
                        if (!$cell){
                            #print "DD - IF NOT CELL: ROW, COL: $row , $col\n" if $debug;
                            $col_table_dd++;
                            next;
                        }
                        #print "DD - IF CELL: ROW, COL, col_table_dd, VALUE: $row , $col , $col_table_dd , ",$cell->value(),"\n" if $debug;
                        if (!($cell->value() =~ /^$/) and ($cell)) {
                            ${$table_dd[$row]}[$col_table_dd] = $cell->value();
                            #print "DD - table_dd, ROW , COL_DD, VALUE, $row, $col_table_dd , ${$table_dd[$row]}[$col_table_dd]\n" if $debug;
                        }
                        $col_table_dd++;
                    }
                }
                #split also dontdel.
                #read dontdel table.
                my @UniqeAddressmapArray = uniq @AddressmapArray;
                for ( my $UniqeIDX = 0 ; $UniqeIDX < scalar @UniqeAddressmapArray ; $UniqeIDX++ ){
                    if ($UniqeAddressmapArray[$UniqeIDX] ~~ @Groups) {
                        #print "BORIS4 - Addressmap $UniqeAddressmapArray[$UniqeIDX] exists in Groups\n";
                    }
                    else {
                        print "NOTE - Addressmap $UniqeAddressmapArray[$UniqeIDX] NOT exists in Groups. LOOP TO NEXT ADDRESSMAP.\n";
                        next;
                    }

                    $TruncFileName = substr($UniqeAddressmapArray[$UniqeIDX], 0, 30);

                    #print "TruncFileName: $TruncFileName\n";
                    create_excel_local("$TruncFileName"); #create new excel file with header
                    my $rowIdx_real;
                    for (my $i = 0; $i < scalar @Groups; $i++) {
                        $rowIdx_real = 0;
                        #print "-$Groups[$i]-\n" if $debug;
                        for (my $rowIdx = 0;$rowIdx< scalar @table_dd ; $rowIdx++){
                            if (!$table_dd[$rowIdx]){#empty line
                                print "empty line = $table_dd[$rowIdx]\n" if $debug;
                                next;   
                            }    
                            my @row = @{$table_dd[$rowIdx]};
                            #print "DD split - row: -@{$table_dd[$rowIdx]}-\n" if $debug;
                            next unless $row[0];
                            #print "UniqeAddressmapArray , row[8]: $UniqeAddressmapArray[$UniqeIDX] , $row[8]\n" if $debug;
                            unless ($UniqeAddressmapArray[$UniqeIDX] eq $row[8]){
                                next;
                            }
                            #print"SPLICE CHECK , ROW:-@row-\n" if $debug;
                            #splice(@row,6,1);
                            my $rowRef = \@row;
                            $worksheet2->write_row($rowIdx_real + 1, 0, $rowRef, $cell_format1);
                            $rowIdx_real++;
                        }
                    }                
                 
                    for (my $rowIdx = 0; $rowIdx < scalar @table_SW_DB_info; $rowIdx++) {
                        #print "CHECK4:rowIdx $rowIdx","\n";
                        if (!$table_SW_DB_info[$rowIdx]){#empty line
                        #        print "empty line = $table_dd[$rowIdx]\n" if $debug;
                            next;   
                        }
                        #next unless $table_SW_DB_info[$rowIdx];
                        my @row = @{$table_SW_DB_info[$rowIdx]};
                        #print "row_array: @row\n";
                        my $rowRef = \@row;
                        $worksheet3->write_row($rowIdx, 0, $rowRef, $cell_format1);
                    }
                    
                    $rowIdx_real = 0;
                    for (my $rowIdx = 0; $rowIdx < scalar @table; $rowIdx++) {
                        next unless $table[$rowIdx];
                        my @row = @{$table[$rowIdx]};
                        unless ($UniqeAddressmapArray[$UniqeIDX] eq $row[3]){
                            next;
                        }
                        my $rowRef = \@row;
                        $worksheet1->write_row($rowIdx_real + 1, 0, $rowRef, $cell_format1);
                        $rowIdx_real++;
                    }
                    push @CopyList , "$UniqeAddressmapArray[$UniqeIDX]";
                }    
            }
            $index = 0;
            until ($fileListSpliced[$index] eq "$RegsXLSX"){
                $index++;
                exit if $index > 50;
            }
            print "INDEX $index\n" if $debug;
            splice(@fileListSpliced, $index, 1);
        }
    } 
    if ($CloseFlag){
        $workbook->close();
        ##### move all splited spreadsheets excel files to local path. #####
        foreach my $file (@CopyList){
            print "file move to local: ${file}_regs.xlsx\n";
            $TruncFileName = substr($file, 0, 30);
            move("$TruncFileName.xlsx", "$LocalPath") or die "Couldn't move file $file, $!";
        }
    }
    print "SplitSpreadSheets function finished working\n" if $debug;
    return @fileListSpliced;
}

sub GetDefines {
    my @rows;
    my $FH_InputTable;
    my $DefPath = "$FindPath/rtl/proj/gbr_common/include";
    my $CARDefPath = "$FindPath/rtl/units/car/src";
    my @files = ("$DefPath/cio_defines.def","$DefPath/cio_switch.def","$CARDefPath/car.def");
    my %Defines;
    my $TempDefValue;
    foreach my $filename (@files){
        open $FH_InputTable, '<', "$filename" or die "Couldn't open file $filename, $!";
        chomp(@rows = <$FH_InputTable>);
        close $FH_InputTable;
        foreach my $row (@rows){
            next if (($row =~ m/timescale/) or ($row =~ m/`define\s+(\w+)\s+\{/) or ($row =~ m/`define\s+(\w+)\s*$/) or ($row =~ m/^\/\//));
            next unless $row =~ m/`define/;
            my($DefName,$DefValue) = $row =~ m/`define\s+(\w+)\s+(.*)/;
            $DefValue =~ s/\s*\/\/.*//;
            $DefValue =~ s/`\w+'h/0x/g;
            $DefValue =~ s/\d+'h/0x/g;
            $DefValue =~ s/\d+'b/0b/g;
            $DefValue =~ s/\d+'d//g;
            $DefValue =~ s/\s*$//;
            $DefValue =~ s/`(\w+)/\$Defines{$1}/g;
            $TempDefValue = eval($DefValue);
            $Defines{$DefName} = $TempDefValue;
            #print "DefName , DefValue: -$DefName- , $DefValue\n";
            #print "HashValue: $Defines{$DefName}\n";
        }
    }
    #print Dumper(\%Defines);
    return %Defines;
}
sub GetVars {
    my @rows;
    my $FH_InputTable;
    my $filename = "$VAR";
    my %Vars;
    my $TempDefValue;
#    foreach my $filename (@files){
    open $FH_InputTable, '<', "$filename" or die "Couldn't open file $filename, $!";
    chomp(@rows = <$FH_InputTable>);
    close $FH_InputTable;
    foreach my $row (@rows){
        my($VarName,$VarValue) = $row =~ m/(\w+)\s+(\[.*\])/;
        $Vars{$VarName} = $VarValue;
        #print "DefName , DefValue: -$DefName- , $DefValue\n";
        #print "HashValue: $Defines{$DefName}\n";
    }
#    }
    #print Dumper(\%Defines);
    return %Vars;
}



sub PrintHelp {
   my $script_name = shift ;
   print <<END ;

Usage: $script_name

            -I[P]     <run with dont delete tab for IP>,
            -m[odel]  <Model Name, Choose what is the model>,
            -d[ebug]  <Debug mode, print debug messagess to the screen>,
            -v[ar]    <Variable file>

END
   exit ;
}
