cmake_minimum_required(VERSION 3.16)

if(NOT EXISTS ${CMAKE_CURRENT_LIST_DIR}/main/generated/model_data.cc)
    message(FATAL_ERROR
        "main/generated/ is missing. Train and export the model first:\n"
        "  cd training && python train.py --out runs/ds_cnn && python export.py --run runs/ds_cnn")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(logguard)
