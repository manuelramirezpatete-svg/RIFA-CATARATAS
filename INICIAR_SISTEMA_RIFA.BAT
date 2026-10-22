@echo off
title Sistema de Control y Venta Online de Rifa Benefica (500 Numeros)
cd /d "%~dp0"
echo ==============================================================================
echo    SISTEMA DE RIFA BENEFICA EN LINEA - CIRUGIA DE CATARATAS
echo    Premio: Aire Acondicionado de Ventana 12.000 BTU
echo    Valor: 5$ | 500 Numeros (001 al 500)
echo ==============================================================================
echo.
echo Iniciando servidor y generando enlace publico para compradores...
start http://localhost:5090/admin
echo.
echo Presione Ctrl + C para detener el sistema.
echo.
python app_rifa.py
pause
