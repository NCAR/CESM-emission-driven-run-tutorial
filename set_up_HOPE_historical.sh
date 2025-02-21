#!/bin/sh

######## Assign Project Number
# Project number to charge for the simulation
export PROJECT_NUM=USIO0040 # this is the account for the emissions-driven tutorial
export CHARGE_ACCOUNT=USIO0040 # this is the account for the emissions-driven tutorial

######## this case will branch off the PI control'

cd '/glade/work/'$USER

mkdir emissions-driven-tutorial

CASEROOT_PARENT='/glade/work/'$USER'/emissions-driven-tutorial'

cd $CASEROOT_PARENT

######### check out the version of CESM from the HOPE ensemble runs:

git clone -b baselines_tag_06 https://github.com/lawrencepj1/CESM2.1.5-CCIS-Ens cesm2.1.5-ccisens-activebvocs

SRCROOT=$CASEROOT_PARENT'/cesm2.1.5-ccisens-activebvocs'

cd $SRCROOT

./manage_externals/checkout_externals

########## set case name and case root path

CASE='b.e21.BHIST_BPRPcmip6.f09_g17.ccisens-reference.esmfirebvoc.001'

CASEROOT=$CASEROOT_PARENT'/'$CASE

######## create the case, first remove any case with the same name

cd $SRCROOT'/cime/scripts'

rm -Rf $CASEROOT '/glade/derecho/scratch/'$USER'/'$CASE '/glade/derecho/scratch/'$USER'/archive/'$CASE

./create_newcase --machine derecho --compset BHIST_BPRPcmip6  --res f09_g17 --case $CASEROOT --pecount L --project $PROJECT_NUM

echo 'Just created the case, now document the code base'

echo $CASEROOT

#########  document code being used as Keith does -----------------------------------------

touch $CASEROOT/code_info.txt

echo '------------------------' >> $CASEROOT/code_info.txt

echo '------------------------' >> $CASEROOT/code_info.txt
cat Externals.cfg >> $CASEROOT/code_info.txt
echo '------------------------' >> $CASEROOT/code_info.txt

echo 'code base documented, setting up the case now...'

###---- set up the case PE count and namelist files ---------------------------

cd $CASEROOT

######### we will be branching off a PI control, making a hybrid run, set PI control as reference case

REFCASE='b.e21.B1850.f09_g17.ccisens-reference.esmfirebvoc.001'

########  xmlchange commands to get the run set up

./xmlchange RUN_TYPE=hybrid
./xmlchange PROJECT=$PROJECT_NUM,CHARGE_ACCOUNT=$CHARGE_ACCOUNT 
./xmlchange RUN_REFCASE=$REFCASE
./xmlchange GET_REFCASE=FALSE
./xmlchange RUN_REFDATE=0051-01-01
./xmlchange RUN_STARTDATE=1850-01-01
./xmlchange JOB_WALLCLOCK_TIME=2:00:00 --subgroup case.run

############# choose the length of run

./xmlchange STOP_OPTION=nmonths,STOP_N=1 ##just do a one month run
./xmlchange JOB_PRIORITY=regular

########### CLM xmlchanges

## turn fire and bvoc emissions on for clm5
./xmlchange --append CLM_BLDNML_OPTS="-fire_emis -megan" 
./xmlchange --append CLM_NAMELIST_OPTS="init_interp_method='general' irrigate=.true."

########## now do case set up 

./case.setup

###### Copy the initial conditions from the PI control to the run directory

REST_DIR='/glade/campaign/cesm/community/bgcwg/HOPE/ccisensinput/initial_conditions_files/b.e21.B1850.f09_g17.ccisens-reference.esmfirebvoc.001/0051-01-01-00000'

cp ${REST_DIR}/* '/glade/derecho/scratch/'$USER'/'$CASE'/run/'.

####### Copy over user_nl and SourceMods from Peter Lawrence's directories

USER_NL_DIR='/glade/campaign/cesm/community/bgcwg/HOPE/ccisensinput/user_nl_files/updated_reference_hist_esmfirebvoc_files'

cp ${USER_NL_DIR}'/user_nl_'* ${CASEROOT}

######## Preview namelists

./preview_namelists

############## now just build the model and submit:

qcmd -A USIO0040 -- ./case.build

./case.submit
