END_VAR


=====BLOCK=====
FVAR_GLOBAL	 
	  DEBUG_MODE: BOOL; //режим отладки ПО - отключает физические выходы ПЛК 
	  dks_simulation: BOOL; //симуляция работы ДКС
	  dsl_sim_1: BOOL;
	  dsl_sim_2: BOOL;
	  
END_VAR

VAR_GLOBAL RETAIN
	GEMER: BOOL; //Общая авария
	RESET_ERR: BOOL; //Сброс ошибок
    HAND_MODE_FLAG: BOOL; //один из механизмов включен в ручном режиме
	MUTE: BOOL; //Откл сирену
	Do_Alarm: BOOL;
	
//Автоматические режимы
	Mode_och: BOOL; //Режим очистки
	with_trier: BOOL;//Использовать триер
	with_pnev: BOOL; //Использовать пневмостол
	to_bigbag: BOOL;
	To_bunk: BOOL; 
	on_ost: BOOL;
	on_vor: BOOL;
	use_1: BOOL;
	use_2: BOOL;
	
//Ворошитель ямы завальной ЯЗТ-10-0Ц-ЛТ (поз. 1) лист 4
	HMI_BNT_vor: BOOL;
	HMI_DA_vor: BOOL;
	HMI_off_next_vor: BOOL;
	HMI_HM_vor: BOOL;
	
//Конвейер SBT-LR-T168/2025-700/8320 (поз. 2) лист 6    
    HMI_OFF_DKS_2: BOOL;
	HMI_OFF_DP_2: BOOL;
    HMI_BTN_2: BOOL;
	HMI_Err_DKS_2: BOOL;
	HMI_Err_DP_2: BOOL;
	HMI_HM_2: BOOL;
	HMI_DA_2: BOOL;
	HMI_off_next_2: BOOL;

//Нория зерновая НС-В.10.10 (поз. 4) лист 7
	HMI_off_DKS_4: BOOL;
	HMI_off_DP_4: BOOL;
	HMI_off_DSL_1_4: BOOL;
	HMI_off_DSL_2_4: BOOL;
	HMI_DA_noria_4: BOOL;
	HMI_BTN_noria_4: BOOL;
	HMI_Err_DKS_4: BOOL;
	HMI_Err_DP_4: BOOL;
	HMI_Err_DSL_4: BOOL;
	HMI_Err_TO_4: BOOL;
	HMI_HM_noria_4: BOOL;
	HMI_off_next_4: BOOL;
	
//Остеобрушиватель ОП-11 (поз. 5) лист 8
    HMI_off_next_ost: BOOL;
	HMI_HM_ost: BOOL;
	HMI_btn_ost: BOOL;	
    HMI_DA_ost: BOOL;
	
//Машина универсальная зерноочистительная МУЗ-8М (поз. 6) лист 9
    HMI_BTN_ksp: BOOL;
	HMI_DA_ksp: BOOL;
	HMI_HM_ksp: BOOL;
	HMI_off_next_ksp: BOOL;

//Машина универсальная зерноочистительная МУЗ-8М (битер) (поз. 6) лист 10
    HMI_BTN_biter: BOOL;
	HMI_DA_biter: BOOL;
	HMI_HM_biter: BOOL;
	HMI_off_next_biter: BOOL;
	
//Вентилятор системы аспирации АС-1 (поз. 7) лист 11
    HMI_DA_fan_asp_1: BOOL;
	HMI_BTN_fan_asp_1: BOOL;
	HMI_HM_fan_asp_1: BOOL;
	HMI_off_next_fan_asp_1: BOOL;

//Затвор шлюзовый ЗШ-17 системы аспирации АС-1 (поз. 7) лист 12
	HMI_off_DKS_shl_1: BOOL;
	HMI_HM_shl_1: BOOL;
	HMI_off_next_shl_1: BOOL;
	HMI_BTN_shl_1: BOOL;
	HMI_Err_DKS_shl_1: BOOL;
	HMI_DA_shl_1: BOOL;
	
//Нория зерновая НС-А.10.08 (поз. 8) лист 13	
    HMI_DA_noria_8: BOOL;
	HMI_BTN_noria_8: BOOL;
	HMI_Err_DKS_8: BOOL;
	HMI_Err_DP_8: BOOL;
	HMI_Err_DSL_8: BOOL;
	HMI_Err_TO_8: BOOL;
	HMI_off_DKS_8: BOOL;
	HMI_off_DP_8: BOOL;
	HMI_off_DSL_1_8: BOOL;
	HMI_off_DSL_2_8: BOOL;
	HMI_HM_noria_8: BOOL;
	HMI_off_next_8: BOOL;
	
//Машина тонкой очистки решетная ТОР-18 (поз. 10) лист 14
    HMI_DA_TOR: BOOL;
	HMI_HM_TOR: BOOL;
	HMI_BTN_TOR: BOOL;
	HMI_off_next_TOR: BOOL;
	
    HMI_DA_TOR_biter: BOOL;
	HMI_HM_TOR_biter: BOOL;
	HMI_BTN_TOR_biter: BOOL;
	HMI_off_next_TOR_biter: BOOL;
	
//Вентилятор системы аспирации АС-2 (поз. 11) лист 16
    HMI_BTN_fan_asp_2: BOOL;
	HMI_HM_fan_asp_2: BOOL;
	HMI_DA_fan_asp_2: BOOL;
	HMI_off_next_fan_asp_2: BOOL;
	
//Затвор шлюзовый ЗШ-17 системы аспирации АС-2 (поз. 11) лист 17
    HMI_DA_shl_2: BOOL;
	HMI_BTN_shl_2: BOOL;
	HMI_Err_DKS_shl_2: BOOL;
	HMI_off_DKS_shl_2: BOOL;
	HMI_HM_shl_2: BOOL;
	HMI_off_next_shl_2: BOOL;

//Нория зерновая НС-А.10.08 (поз. 12) лист 18
    HMI_DA_noria_12: BOOL;
	HMI_BTN_noria_12: BOOL;
	HMI_Err_DKS_12: BOOL;
	HMI_Err_DP_12: BOOL;
	HMI_Err_DSL_12: BOOL;
	HMI_Err_TO_12: BOOL;
	HMI_off_next_12: BOOL;
	HMI_HM_noria_12: BOOL;
	HMI_off_DSL_2_12: BOOL;
	HMI_off_DSL_1_12: BOOL;
	HMI_off_DP_12: BOOL;
	HMI_off_DKS_12: BOOL;
	
//Переключатель потока ППМ-2.160 0/45 (поз. 13.1) лист 19
    HMI_DA_flow_1: BOOL;
	HMI_HM_fw_1: BOOL;
	HMI_BTN_fw_1_1: BOOL;
	HMI_BTN_fw_2_1: BOOL;
    HMI_Err_swap_1: BOOL;
	HMI_Err_conc_1: BOOL;
	
//Переключатель потока ППМ-2.160 0/45 (поз. 13.2) лист 20
    HMI_DA_flow_2: BOOL;
	HMI_BTN_fw_1_2: BOOL;
	HMI_BTN_fw_2_2: BOOL;
	HMI_Err_swap_2: BOOL;
	HMI_Err_conc_2: BOOL;
	HMI_HM_fw_2: BOOL;
	
//Двигатель N1 триерного блока БТ-7/2 (поз. 14.1) лист 21
	HMI_HM_trier_1: BOOL;
	HMI_btn_trier_1: BOOL;
	HMI_off_next_trier_1: BOOL;
	HMI_DA_trier_1: BOOL;	
	
//Двигатель N2 триерного блока БТ-7/2 (поз. 14.1) лист 22
    HMI_BTN_trier_2_1: BOOL;
	HMI_DA_trier_2_1: BOOL;
	HMI_off_next_trier_2_1: BOOL;
	HMI_HM_trier_2_1: BOOL;
	
//Двигатель N1 триерного блока БТ-7/2 (поз. 14.2) лист 23
	HMI_HM_trier_1_2: BOOL;
	HMI_btn_trier_1_2: BOOL;
	HMI_off_next_trier_1_2: BOOL;
	HMI_DA_trier_1_2: BOOL;	

//Двигатель N2 триерного блока БТ-7/2 (поз. 14.2) лист 24
    HMI_BTN_trier_2_2: BOOL;
	HMI_DA_trier_2_2: BOOL;
	HMI_off_next_trier_2_2: BOOL;
	HMI_HM_trier_2_2: BOOL;
	
//Нория зерновая НС-А.10.11 (поз. 15) лист 25
    HMI_DA_noria_15: BOOL;
	HMI_BTN_noria_15: BOOL;
	HMI_Err_DKS_15: BOOL;
	HMI_Err_DP_15: BOOL;
	HMI_Err_DSL_15: BOOL;
	HMI_Err_TO_15: BOOL;
	HMI_off_DKS_15: BOOL;
	HMI_off_DP_15: BOOL;
	HMI_off_DSL_1_15: BOOL;
	HMI_off_DSL_2_15: BOOL;
	HMI_HM_noria_15: BOOL;
	HMI_off_next_15: BOOL;
	
//Стол пневмосортировательный СП-200 (вентилятор) (поз. 18) лист 26
    HMI_BTN_fan_pnev: BOOL;
	HMI_DA_fan_pnev: BOOL;
	HMI_HM_fan_pnev: BOOL;
	HMI_off_next_fan_pnev: BOOL;	
	
//Стол пневмосортировательный СП-200 (поз. 18) лист 27
   	HMI_DA_pnev: BOOL;
	HMI_BTN_pnev: BOOL;
	HMI_HM_pnev: BOOL;
	HMI_off_next_pnev: BOOL;
	
//Вентилятор системы аспирации АС-3 (поз. 19) лист 28
    HMI_BTN_fan_asp_3: BOOL;
	HMI_HM_fan_asp_3: BOOL;
	HMI_DA_fan_asp_3: BOOL;
	HMI_off_next_fan_asp_3: BOOL;
	
//Затвор шлюзовый ЗШ-17 системы аспирации АС-3 (поз. 24.3) лист 27
    HMI_DA_shl_3: BOOL;
	HMI_BTN_shl_3: BOOL;
	HMI_Err_DKS_shl_3: BOOL;
	HMI_off_DKS_shl_3: BOOL;
	HMI_HM_shl_3: BOOL;
	HMI_off_next_shl_3: BOOL;

//Нория зерновая Н3-В.10.10 (поз. 20) лист 30
    HMI_off_DKS_20: BOOL;
	HMI_off_DP_20: BOOL;
	HMI_off_DSL_1_20: BOOL;
	HMI_off_DSL_2_20: BOOL;
	HMI_DA_noria_20: BOOL;
	HMI_BTN_noria_20: BOOL;
	HMI_Err_DKS_20: BOOL;
	HMI_Err_DP_20: BOOL;
	HMI_Err_DSL_20: BOOL;
	HMI_Err_TO_20: BOOL;
	HMI_HM_noria_20: BOOL;
	HMI_off_next_20: BOOL;

//Конвейер шнековый КШИ-200 10М/10 (поз. 22.1) лист 31
    HMI_off_DKS_22_1: BOOL;
	HMI_off_DP_22_1: BOOL;
	HMI_hm_conv_22_1: BOOL;
	HMI_off_conv_22_1: BOOL;
	HMI_BTN_conv_22_1: BOOL;
	HMI_DA_conv_22_1: BOOL;
	HMI_Err_DKS_22_1: BOOL;
	HMI_Err_DP_22_1: BOOL;
	
//Конвейер шнековый КШИ-200 9М/15 (поз. 22.2) лист 32	
	HMI_off_DKS_22_2: BOOL;
	HMI_off_DP_22_2: BOOL;
	HMI_hm_conv_22_2: BOOL;
	HMI_DA_conv_22_2: BOOL;
	HMI_BTN_conv_22_2: BOOL;
	HMI_Err_DKS_22_2: BOOL;
	HMI_Err_DP_22_2: BOOL;
	HMI_off_conv_22_2: BOOL;

//Конвейер шнековый КШИ-150 8М/5 (поз. 22.3) лист 33
    HMI_DA_conv_22_3: BOOL;
	HMI_BTN_conv_22_3: BOOL;
	HMI_Err_DKS_22_3: BOOL;
	HMI_Err_DP_22_3: BOOL;
	HMI_off_DKS_22_3: BOOL;
	HMI_off_DP_22_3: BOOL;
	HMI_hm_conv_22_3: BOOL;
	HMI_off_conv_22_3: BOOL;
	
//Конвейер шнековый КШИ-150 4М/5 (поз. 22.4) лист 34	
    HMI_DA_conv_22_4: BOOL;
	HMI_BTN_conv_22_4: BOOL;
	HMI_Err_DKS_22_4: BOOL;
	HMI_Err_DP_22_4: BOOL;
	HMI_off_DKS_22_4: BOOL;
	HMI_off_DP_22_4: BOOL;
	HMI_hm_conv_22_4: BOOL;
	HMI_off_conv_22_4: BOOL;
	
//Конвейер шнековый КШИ-150 9М/5 (поз. 22.5) лист 35
    HMI_DA_conv_22_5: BOOL;
	HMI_BTN_conv_22_5: BOOL;
	HMI_Err_DKS_22_5: BOOL;
	HMI_Err_DP_22_5: BOOL;
	HMI_off_DKS_22_5: BOOL;
	HMI_off_DP_22_5: BOOL;
	HMI_hm_conv_22_5: BOOL;
	HMI_off_conv_22_5: BOOL;

//Нория зерновая Н3-В.20.11 (поз. 23) лист 30
    HMI_off_DKS_23: BOOL;
	HMI_off_DP_23: BOOL;
	HMI_off_DSL_1_23: BOOL;
	HMI_off_DSL_2_23: BOOL;
	HMI_DA_noria_23: BOOL;
	HMI_BTN_noria_23: BOOL;
	HMI_Err_DKS_23: BOOL;
	HMI_Err_DP_23: BOOL;
	HMI_Err_DSL_23: BOOL;
	HMI_Err_TO_23: BOOL;
	HMI_HM_noria_23: BOOL;
	HMI_off_next_23: BOOL;
	
//Нория зерновая Н3-В.20.11 (поз. 24) лист 31
    HMI_off_DKS_24: BOOL;
	HMI_off_DP_24: BOOL;
	HMI_off_DSL_1_24: BOOL;
	HMI_off_DSL_2_24: BOOL;
	HMI_DA_noria_24: BOOL;
	HMI_BTN_noria_24: BOOL;
	HMI_Err_DKS_24: BOOL;
	HMI_Err_DP_24: BOOL;
	HMI_Err_DSL_24: BOOL;
	HMI_Err_TO_24: BOOL;
	HMI_HM_noria_24: BOOL;
	HMI_off_next_24: BOOL;
END_VAR

=====BLOCK=====
PROGRAM Modes
VAR
