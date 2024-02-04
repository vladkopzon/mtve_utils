#!/usr/intel/bin/perl -w
##########################################################################
# The script target:                                                     #
# Recieve as input excel file and convert it to CSV file.                #
# Support on excel with multiple spreadsheets to multiple CSV files.     #
# Support on Registers excel converting and regular excel converting.    #
#                                                                        #
##########################################################################
#                                                                        #
# File:            xlsx2csv.pl                                           #
# Author:          Boris Dikarev                                         #
# Date Created:    06/11/2019                                            #
#                                                                        #
##########################################################################

use strict;
use warnings;

# Standard libraries
use lib qw(/usr/intel/pkgs/perl/5.20.1-threads/lib64/module/r1/); # will add those dirs to @INC
use Getopt::Long ;
use Spreadsheet::XLSX;
use Spreadsheet::ParseXLSX;
use Spreadsheet::WriteExcel;
use Excel::Writer::XLSX;
use File::Copy;
use open ':std', ':encoding(utf-8)';
##########################################################################
# GetOpts Variables
##########################################################################
my $XLSXFile;
my $Register;
my $debug;
my $Help;

GetOptions("xlsxfile=s"      => \$XLSXFile        ,
           "register"        => \$Register        ,
           "debug"           => \$debug           ,
           "help"            => \$Help          ) || die PrintHelp($0) ;

PrintHelp($0) if (defined $Help or not defined $XLSXFile);

##########################################################################
# Global Variables
##########################################################################
my $parser = Spreadsheet::ParseXLSX->new;
my $workbook = $parser->parse("$XLSXFile");
if (!defined $workbook) {
    die $parser->error(), ".\n";
}
my $RealRowStart;
my $DDsheetIDX;
my $worksheet_idx;
my $worksheet;
my $worksheetName;
my $ResultsDir = "xlsx2csv_results";
system("mkdir $ResultsDir");
################    Find the relevant spreadsheets  ################
my $worksheet_count = $workbook->worksheet_count();
print "number of Original worksheets is: $worksheet_count\n" if $debug;
if ($Register){
    for ($worksheet_idx = 0; $worksheet_idx < $worksheet_count; $worksheet_idx++){
        $worksheet = $workbook->worksheet($worksheet_idx);
        $worksheetName = $worksheet->get_name();
        if ($worksheetName eq "dont_delete") {
            $DDsheetIDX = $worksheet_idx;
        }
    }
}
else{
    $DDsheetIDX = $worksheet_count;
}
################    Loop on relevant spreadsheets  ################
print "number of Relevant worksheets is: $DDsheetIDX\n" if $debug;
for ($worksheet_idx = 0; $worksheet_idx < $DDsheetIDX; $worksheet_idx++){
    ################    Parsing Excel sheet  ################
    $worksheet = $workbook->worksheet($worksheet_idx);
    $worksheetName = $worksheet->get_name();   
    print "Parsing WorkSheet: ", $worksheetName, "\n" if $debug;
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
        
        if (not $StartFlag and $cell_0->value() =~ /Owner/ and $Register) {
            $RealRowStart = $row;
            $StartFlag = 1;
            print "RealRowStart: $RealRowStart\n" if $debug;
        }
        else {
            $RealRowStart = $row_min;
        }
        if (((not $cell_0) or $cell_0->value() =~ /^$/) and $StartFlag and $Register) {
            $row_max = $row - 1;
            last;
        }
    }
    my $cell_value;
    my ($col_min, $col_max) = $worksheet->col_range();
    open my $FH_SpreadsheetFile, '>', "$worksheetName.csv" or die "Couldn't open file $worksheetName.csv, $!"; 
    for my $row ($RealRowStart .. $row_max) {
        for my $col ($col_min .. $col_max) {
            my $cell = $worksheet->get_cell($row, $col);
            if ($col < $col_max) {
                if (!$cell) {
                    print $FH_SpreadsheetFile ",";
                }
                else{
                    $cell_value = $cell->value();
                    print $FH_SpreadsheetFile "$cell_value,";
                }
            }
            elsif ($col == $col_max){
                if (!$cell) {
                    print $FH_SpreadsheetFile "";
                }
                else{
                    $cell_value = $cell->value();
                    print $FH_SpreadsheetFile "$cell_value";
                }
             
            }
        }    
        print $FH_SpreadsheetFile "\n";
    }
    close $FH_SpreadsheetFile;
    move("$worksheetName.csv", "$ResultsDir/") or die "Couldn't copy file $worksheetName.csv";
}

sub PrintHelp {
   my $script_name = `basename $0`;
   chomp($script_name);
   my $space0 = $script_name;
   $space0 =~ s/./ /g ;
   print <<END ;

Usage: $script_name -x[lsx] <xlsx_file.xlsx>
       $space0      -x[lsx]      ==> input excel file.
       $space0      -r[egister]  ==> Converting Registrs excels files ( with dont_delete tab and etc.).
       $space0      -d[ebug]     ==> Debug mode, print debug messagess to the screen>.
               
END
   exit;
}
