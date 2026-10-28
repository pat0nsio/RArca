# Validación del juez (20 respuestas)

Corrida: `eval/resultados/2026-10-27T2109_qwen3-8b.jsonl` (generador qwen3:8b, juez llama3.1:8b).
Completá las dos líneas `Tu …` de cada bloque. Exactitud: correcta / parcial / incorrecta. Fiel: si / no
(fiel = todo lo que afirma la respuesta es cierto según las fuentes; una respuesta incompleta puede ser fiel).

## #2 [dato] ¿Qué valor hay que enviar en el tag service al pedir el ticket de acceso al WSAA para usar el WSFEv1, y cuánto dura ese ticket?

**Referencia:** El valor "wsfe". El ticket de acceso dura 12 horas.

**Respuesta del sistema:** Se debe enviar el tag service con el valor "wsfe" y la duración del ticket es de 12 hs [1].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #5 [dato] ¿Qué valores acepta el campo Concepto en FECAESolicitar?

**Referencia:** 1 Productos, 2 Servicios, 3 Productos y Servicios.

**Respuesta del sistema:** El campo Concepto en FECAESolicitar acepta los valores 1, 2 y 3, que corresponden a Productos, Servicios y Productos y Servicios respectivamente [5].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #7 [dato] ¿Qué significan los valores A, R y P del campo Resultado en la respuesta de FECAESolicitar?

**Referencia:** A = Aprobado, R = Rechazado, P = Parcial.

**Respuesta del sistema:** El campo "Resultado" en la respuesta de FECAESolicitar puede tomar los valores "A", "R" o "P", que indican el estado del comprobante. [1]

- **A**: Aprobado (el comprobante fue autorizado).
- **R**: Rechazado (el comprobante no fue autorizado).
- **P**: Pendiente (el comprobante está en proceso de autorización).

[1]

Juez → exactitud: parcial | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #8 [dato] ¿Qué método indica cuántos comprobantes se pueden mandar como máximo en un request de FECAESolicitar?

**Referencia:** FECompTotXRequest. Devuelve el campo RegXReq con la cantidad máxima de registros por request de FECAESolicitar y FECAEARegInformativo.

**Respuesta del sistema:** El método que indica cuántos comprobantes se pueden mandar como máximo en un request de FECAESolicitar es FECompTotXRequest [3].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #10 [dato] ¿Qué devuelve el método FEDummy?

**Referencia:** El estado de tres servidores: AppServer (aplicaciones), DbServer (base de datos) y AuthServer (autenticación). Sirve para verificar el funcionamiento de la infraestructura.

**Respuesta del sistema:** El método FEDummy devuelve la comprobación vía “ping” de los elementos principales de infraestructura del servicio [2].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #14 [dato] ¿Qué fechas son obligatorias al facturar servicios por WSFEv1?

**Referencia:** FchServDesde, FchServHasta y FchVtoPago, en formato yyyymmdd. FchServHasta no puede ser menor a FchServDesde y FchVtoPago debe ser igual o posterior a la fecha del comprobante.

**Respuesta del sistema:** Las fechas obligatorias al facturar servicios por WSFEv1 son FchServDesde y FchServHasta [1].

Juez → exactitud: parcial | fiel: no

- Tu exactitud: 
- Tu fiel: 

## #15 [dato] ¿Qué cotización hay que informar en MonCotiz si el comprobante es en pesos?

**Referencia:** 1. Para PES (pesos argentinos) la cotización debe ser 1.

**Respuesta del sistema:** Para pesos, la cotización debe ser 1 [4].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #17 [dato] ¿A qué correo se hacen las consultas sobre normativa de factura electrónica?

**Referencia:** facturaelectronica@arca.gov.ar. Las consultas funcionales de homologación van a wsfev1@arca.gov.ar y las de producción a sri@arca.gov.ar.

**Respuesta del sistema:** facturaelectronica@arca.gov.ar [1].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #23 [procedimiento] ¿Cómo sé qué número ponerle al próximo comprobante?

**Referencia:** Consultar FECompUltimoAutorizado para el tipo de comprobante y punto de venta, y usar ese número + 1: CbteDesde debe ser mayor en 1 al último informado (validación 10016).

**Respuesta del sistema:** Para conocer el número del próximo comprobante, debes utilizar el servicio "Recuperador de último valor de comprobante registrado" (FECompUltimoAutorizado) [1]. Este servicio retorna el último número de comprobante autorizado para el punto de venta y tipo de comprobante enviado. El número del próximo comprobante será el siguiente al último registrado.

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #24 [procedimiento] ¿Cuándo y cómo se solicita un CAEA?

**Referencia:** Con FECAEASolicitar, indicando Periodo (AAAAMM) y Orden (1 o 2). La quincena 1 va del 1 al 15 y la 2 del 16 al último día del mes. Se puede pedir desde 5 días corridos antes del inicio de la quincena hasta su último día. No puede existir otro CAEA para la misma CUIT, periodo y orden.

**Respuesta del sistema:** Se solicita un CAEA dentro de cada quincena y hasta 5 días corridos anteriores al comienzo de cada quincena [1]. Para solicitarlo, se debe enviar una solicitud al WSFEv1 con los datos de autenticación (Token, Sign y Cuit), el período en formato AAAAMM y el orden (1 o 2) que corresponda a la quincena [3].

Juez → exactitud: parcial | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #26 [procedimiento] ¿Cómo informo una factura con varias alícuotas de IVA?

**Referencia:** En el array IVA, un registro por alícuota con Id (según FEParamGetTiposIva), BaseImp e Importe. El Id no puede repetirse: hay que totalizar por alícuota. La suma de los importes debe coincidir con ImpIVA. En comprobantes C no se informa el array.

**Respuesta del sistema:** Para informar una factura con varias alícuotas de IVA, se debe utilizar el array `<ar:Iva>` dentro del mensaje de solicitud, incluyendo múltiples elementos `<ar:AlicIva>`, cada uno con el código de alícuota, la base imponible y el importe correspondiente [1]. Cada alícuota debe estar asociada a su base imponible y el importe del IVA calculado [4].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #28 [procedimiento] ¿Cómo mando varios comprobantes en un solo request de FECAESolicitar?

**Referencia:** En FeCabReq, CantReg igual a la cantidad de registros del detalle; todos deben ser del mismo CbteTipo y del mismo PtoVta. La cantidad no puede superar RegXReq (FECompTotXRequest). Las FCE MiPyMEs van de a una.

**Respuesta del sistema:** Para enviar varios comprobantes en un solo request de FECAESolicitar, debes incluir múltiples elementos `<ar:FECAEDetRequest>` dentro de `<ar:FeDetReq>`, cada uno correspondiente a un comprobante [5].

Juez → exactitud: parcial | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #30 [procedimiento] ¿Cómo emito una factura B a un consumidor final sin identificarlo?

**Referencia:** Con DocTipo 99 y DocNro 0 (validación 10015 del WSFEv1). Según la RG 5700/2025, vigente desde el 29/05/2025, hay que identificar al consumidor final (CUIT, CUIL, CDI o DNI) solo si la operación es igual o superior a $10.000.000; el comprobante lleva siempre la leyenda "A CONSUMIDOR FINAL".

**Respuesta del sistema:** Para emitir una factura B a un consumidor final sin identificarlo, se deberá informar el campo "Nombre y Apellido" con el valor "Consumidor Final" y el campo "Documento" con el valor "00000000" [1].

Juez → exactitud: incorrecta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #33 [comparacion] ¿Qué diferencia hay entre CAE y CAEA?

**Referencia:** El CAE se pide comprobante por comprobante con FECAESolicitar. El CAEA es un código anticipado por quincena (FECAEASolicitar) y los comprobantes se informan después con FECAEARegInformativo. Según la RG 5782/2025, el CAEA solo se usa para contingencias.

**Respuesta del sistema:** La diferencia entre CAE y CAEA radica en su régimen de aplicación y uso. El CAE (Código de Autorización Electrónico) se utiliza para la emisión de comprobantes electrónicos en el régimen general, mientras que el CAEA (Código de Autorización Electrónico Anticipado) se aplica exclusivamente en situaciones de contingencia, según la RG 5782/2025 [4]. Además, el CAEA requiere que el domicilio esté asociado a un punto de venta activo bajo la modalidad CAE o Controlador Fiscal de Nueva Tecnología como modalidad principal [1].

Juez → exactitud: parcial | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #34 [comparacion] ¿Qué diferencia hay entre una validación excluyente y una no excluyente?

**Referencia:** Si falla una excluyente, el comprobante se rechaza. Si falla una no excluyente, se aprueba con observaciones y se asigna CAE con su vencimiento.

**Respuesta del sistema:** Las validaciones excluyentes provocan un rechazo si no se superan, mientras que las no excluyentes aprueban la solicitud con observaciones [1].

Juez → exactitud: correcta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #37 [comparacion] ¿Qué diferencia hay entre WSFEv1 y WSFEX?

**Referencia:** WSFEv1 (RG 4291) autoriza comprobantes A, B, C y M; el service del WSAA es "wsfe" y se usa FECAESolicitar. WSFEX (RG 2758) autoriza comprobantes de exportación E (tipos 19, 20 y 21); el service es "wsfex" y se usa FEXAuthorize.

**Respuesta del sistema:** WSFEv1 y WSFEX son servicios web distintos con funcionalidades diferentes. WSFEv1 se utiliza para la autorización de comprobantes electrónicos mediante CAE y CAEA, mientras que WSFEX se utiliza para la emisión de comprobantes electrónicos [2].

Juez → exactitud: incorrecta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #40 [comparacion] ¿Qué diferencia hay entre FECompConsultar y FECompUltimoAutorizado?

**Referencia:** FECompConsultar devuelve un comprobante puntual (tipo, punto de venta y número) con todos los datos enviados, el CAE y su vencimiento. FECompUltimoAutorizado devuelve el número del último comprobante autorizado para un tipo y punto de venta.

**Respuesta del sistema:** FECompUltimoAutorizado devuelve el último número de comprobante autorizado para un tipo de comprobante, cuit y punto de venta [5], mientras que FECompConsultar permite consultar comprobantes emitidos y su código [4]. [5] [4]

Juez → exactitud: parcial | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #47 [norma_modificada] ¿Puedo usar CAEA como modalidad principal de facturación?

**Referencia:** No. Según la RG 5782/2025, el CAEA solo se usa para contingencias. Los puntos de venta CAEA deben estar en un domicilio con un punto de venta CAE o un Controlador Fiscal de Nueva Tecnología como modalidad principal (versión 4.6 del 01/08/2026, validaciones 15016 y 15017).

**Respuesta del sistema:** No, no puedes usar CAEA como modalidad principal de facturación [1].

Juez → exactitud: correcta | fiel: no

- Tu exactitud: 
- Tu fiel: 

## #48 [norma_modificada] ¿Desde cuándo se puede informar la condición frente al IVA del receptor y qué pasa si el valor no es válido?

**Referencia:** Desde el 6 de abril de 2025 se puede enviar en CondicionIVAReceptorId, de forma opcional hasta que rija la obligatoriedad que el manual atribuye a la RG 5616. Si el valor no es válido, en CAE se rechaza y en CAEA se observa; si no existe, se rechaza en ambos.

**Respuesta del sistema:** La condición frente al IVA del receptor se puede informar desde la implementación de la Resolución General N° 5616, la cual establece que este campo resulta obligatorio [4]. Si el valor no es válido, se generará un error con el código 10245, indicando que el campo Condición Frente al IVA del receptor no es válido [4].

Juez → exactitud: incorrecta | fiel: si

- Tu exactitud: 
- Tu fiel: 

## #49 [norma_modificada] Al informar comprobantes emitidos con CAEA, ¿tengo que informar la fecha y hora de generación?

**Referencia:** Sí. Desde la versión 4.6 (01/08/2026, RG 5782) todos los puntos de venta CAEA son de contingencia, y para esos CbteFchHsGen es obligatorio (validación excluyente 1440), con formato yyyymmddhhmiss.

**Respuesta del sistema:** No, no es obligatorio informar la fecha y hora de generación al informar comprobantes emitidos con CAEA. Solo se requiere la fecha del comprobante [2].

Juez → exactitud: incorrecta | fiel: no

- Tu exactitud: 
- Tu fiel: 
