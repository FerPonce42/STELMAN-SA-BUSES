from flask import Flask, render_template, request, redirect, session
from config import get_connection
from flask import  url_for, flash
from config import get_connection
import re

app = Flask(__name__)
app.secret_key = "clave_segura_cualquiera"

# Página pública principal
@app.route("/")
def index():
    # Intentar obtener buses y horarios desde la base de datos; si falla, pasar listas vacíaaas
    buses = []
    horarios = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Obtener buses con su ruta asociada si existe
        # Seleccionar campos existentes en el volcado SQL (no hay columna 'estado')
        cursor.execute("SELECT b.id_bus, b.placa, b.modelo, b.marca, b.color, b.ultima_revision, r.letra AS ruta_letra FROM bus b LEFT JOIN ruta r ON b.id_ruta = r.id_ruta ORDER BY b.id_bus")
        buses = cursor.fetchall()

        # Intentar obtener horarios desde una tabla comúnmente llamada 'horario' o 'horarios'
        try:
            cursor.execute("SELECT * FROM horario ORDER BY id_horario LIMIT 50")
            horarios = cursor.fetchall()
        except Exception:
            try:
                cursor.execute("SELECT * FROM horarios ORDER BY id_horario LIMIT 50")
                horarios = cursor.fetchall()
            except Exception:
                # Si no existe tabla de horarios, dejamos lista vacía
                horarios = []

        cursor.close()
        conn.close()
    except Exception:
        # En caso de error de conexión, dejar variables vacías y permitir que la vista muestre un mensaje
        buses = []
        horarios = []

    return render_template("public/index.html", buses=buses, horarios=horarios)

# Página pública con rutas
@app.route("/rutas")
def rutas():
    # Obtener rutas y sus paraderos desde la base de datos
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM ruta ORDER BY id_ruta")
    rutas = cursor.fetchall()

    # Para cada ruta, obtener paraderos asociados
    for r in rutas:
        cursor.execute("SELECT id_paradero, nombre_paradero, ubicacion FROM paradero WHERE id_ruta=%s ORDER BY id_paradero", (r['id_ruta'],))
        paraderos = cursor.fetchall()
        r['paraderos'] = paraderos

    # Construir lista de paraderos con coordenadas si existen (lat, lng)
    paraderos_coords = []
    for r in rutas:
        for p in r.get('paraderos', []):
            # buscar claves lat/lng en el dict (si la BD las tuviera)
            lat = p.get('lat') if isinstance(p, dict) else None
            lng = p.get('lng') if isinstance(p, dict) else None
            if lat is not None and lng is not None:
                try:
                    paraderos_coords.append({
                        'name': p.get('nombre_paradero'),
                        'lat': float(lat),
                        'lng': float(lng),
                        'ruta': r.get('letra')
                    })
                except Exception:
                    # ignorar valores no numéricos
                    pass

    cursor.close()
    conn.close()
    return render_template("public/rutas.html", rutas=rutas, paraderos_coords=paraderos_coords)


@app.route("/contac", methods=["GET", "POST"])
def contac():
    if request.method == "POST":
        # Aquí podríamos procesar el formulario; por ahora no guardamos nada
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        mensaje = request.form.get('mensaje')
        # Simplemente devolvemos la misma página con un agradecimiento (no persistimos)
        return render_template("public/contac.html", enviado=True, nombre=nombre)
    return render_template("public/contac.html")


# Login supervisores
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        clave = request.form.get("clave")

        try:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True)
            # Asegúrate que las columnas se llamen USUARIO y CONTRASENA en tu BD
            cursor.execute("SELECT * FROM supervisor WHERE USUARIO=%s AND CONTRASENA=%s", (usuario, clave))
            supervisor = cursor.fetchone()
            cursor.close()
            conn.close()
        except Exception as e:
            # error de conexión/consulta
            return render_template("auth/login.html", error=f"Error de BD: {e}")

        if not supervisor:
            return render_template("auth/login.html", error="Credenciales incorrectas")

        # --- Aquí guardamos en sesión lo necesario para filtrar luego ---
        # guardamos el objeto completo (útil para mostrar datos)...
        session["supervisor"] = supervisor
        # ...y guardamos el id por separado para acceso fácil:
        session["supervisor_id"] = supervisor.get("id_empleado")  # <-- aquí está el ID
        # Intentamos extraer/guardar la ruta que supervise (si tu tabla tiene 'area_encargada' o similar)
        route_id = None
        route_letra = None
        area = supervisor.get('area_encargada') if isinstance(supervisor, dict) else None
        if area:
            # ejemplo: extraer una letra (ajusta el regex si tu formato es distinto)
            m = re.search(r"\b([A-Z])\b", area, re.IGNORECASE)
            if m:
                route_letra = m.group(1).upper()
                try:
                    conn2 = get_connection()
                    cur2 = conn2.cursor(dictionary=True)
                    cur2.execute("SELECT id_ruta FROM ruta WHERE letra=%s", (route_letra,))
                    rr = cur2.fetchone()
                    if rr:
                        route_id = rr.get('id_ruta')
                    cur2.close()
                    conn2.close()
                except Exception:
                    route_id = None

        if route_id:
            session['route_id'] = route_id
            session['route_letra'] = route_letra
        else:
            # si no tiene ruta, eliminar claves por si acaso
            session.pop('route_id', None)
            session.pop('route_letra', None)

        # ya autenticado
        return redirect("/dashboard")

    # GET -> mostrar formulario
    return render_template("auth/login.html")


# Dashboard solo supervisores
@app.route("/dashboard")
def dashboard():
    if "supervisor" not in session:
        return redirect("/login")
    # Obtener estadísticas más completas para el dashboard
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Totales básicos (filtrados por ruta si existe)
    route_filter = ''
    params = []
    if session.get('route_id'):
        route_filter = ' WHERE b.id_ruta = %s '
        params = [session.get('route_id')]

    cursor.execute(f"SELECT COUNT(*) AS total_buses FROM bus b {route_filter}", params)
    total_buses = cursor.fetchone().get('total_buses', 0)
    # Empleados relacionados con la ruta (via bus o caja)
    if session.get('route_id'):
        cursor.execute("SELECT COUNT(DISTINCT e.id_empleado) AS total_empleados FROM empleado e LEFT JOIN bus b ON e.id_empleado=b.id_empleado LEFT JOIN regstro_caja rc ON e.id_empleado=rc.id_empleado WHERE (b.id_ruta=%s OR rc.id_ruta=%s)", (session['route_id'], session['route_id']))
        total_empleados = cursor.fetchone().get('total_empleados', 0)
    else:
        cursor.execute("SELECT COUNT(*) AS total_empleados FROM empleado")
        total_empleados = cursor.fetchone().get('total_empleados', 0)

    # Desglose: choferes y cobradores
    if session.get('route_id'):
        # Choferes: asociados a buses de la ruta
        cursor.execute("SELECT COUNT(DISTINCT c.id_empleado) AS choferes_count FROM chofer c LEFT JOIN bus b ON c.id_empleado = b.id_empleado WHERE b.id_ruta=%s", (session['route_id'],))
        choferes_count = cursor.fetchone().get('choferes_count', 0)
        # Cobradores: mostrar siempre todos los cobradores (sin filtrar por ruta)
        cursor.execute("SELECT COUNT(*) AS cobradores_count FROM cobrador")
        cobradores_count = cursor.fetchone().get('cobradores_count', 0)
    else:
        cursor.execute("SELECT COUNT(*) AS choferes_count FROM chofer")
        choferes_count = cursor.fetchone().get('choferes_count', 0)
        cursor.execute("SELECT COUNT(*) AS cobradores_count FROM cobrador")
        cobradores_count = cursor.fetchone().get('cobradores_count', 0)

    if session.get('route_id'):
        cursor.execute("SELECT IFNULL(SUM(monto),0) AS total_recaudado FROM regstro_caja WHERE id_ruta=%s", (session['route_id'],))
        total_recaudado = cursor.fetchone().get('total_recaudado', 0)
    else:
        cursor.execute("SELECT IFNULL(SUM(monto),0) AS total_recaudado FROM regstro_caja")
        total_recaudado = cursor.fetchone().get('total_recaudado', 0)

    if session.get('route_id'):
        cursor.execute("SELECT COUNT(*) AS total_rutas FROM ruta WHERE id_ruta=%s", (session['route_id'],))
        total_rutas = cursor.fetchone().get('total_rutas', 0)
    else:
        cursor.execute("SELECT COUNT(*) AS total_rutas FROM ruta")
        total_rutas = cursor.fetchone().get('total_rutas', 0)

    if session.get('route_id'):
        cursor.execute("SELECT COUNT(*) AS total_incidencias FROM incdncia_oprtva i LEFT JOIN bus b ON i.id_bus = b.id_bus WHERE b.id_ruta=%s", (session['route_id'],))
        total_incidencias = cursor.fetchone().get('total_incidencias', 0)
    else:
        cursor.execute("SELECT COUNT(*) AS total_incidencias FROM incdncia_oprtva")
        total_incidencias = cursor.fetchone().get('total_incidencias', 0)

    # Conteo de buses por ruta (para gráfico)

    if session.get('route_id'):
        cursor.execute("SELECT r.letra AS ruta, COUNT(b.id_bus) AS buses_count FROM ruta r LEFT JOIN bus b ON r.id_ruta = b.id_ruta WHERE r.id_ruta=%s GROUP BY r.id_ruta ORDER BY r.letra", (session['route_id'],))
    else:
        cursor.execute("SELECT r.letra AS ruta, COUNT(b.id_bus) AS buses_count FROM ruta r LEFT JOIN bus b ON r.id_ruta = b.id_ruta GROUP BY r.id_ruta ORDER BY r.letra")
    buses_por_ruta = cursor.fetchall()

    # Incidencias recientes
    if session.get('route_id'):
        cursor.execute("SELECT i.id_incdncia_oprtva AS id, i.fecha, i.descripccion, i.estado FROM incdncia_oprtva i LEFT JOIN bus b ON i.id_bus=b.id_bus WHERE b.id_ruta=%s ORDER BY i.fecha DESC LIMIT 6", (session['route_id'],))
    else:
        cursor.execute("SELECT id_incdncia_oprtva AS id, fecha, descripccion, estado FROM incdncia_oprtva ORDER BY fecha DESC LIMIT 6")
    incidencias_recientes = cursor.fetchall()

    # Nombre del supervisor (obtener desde empleado si existe id_empleado)
    sup = session.get('supervisor', {})
    supervisor_nombre = None
    id_emp = sup.get('id_empleado') if isinstance(sup, dict) else None
    if id_emp:
        try:
            cursor.execute("SELECT nombre, apellido FROM empleado WHERE id_empleado=%s", (id_emp,))
            row = cursor.fetchone()
            if row:
                supervisor_nombre = f"{row.get('nombre')} {row.get('apellido')}"
        except Exception:
            supervisor_nombre = None

    cursor.close()
    conn.close()

    return render_template(
        "supervisor/dashboard.html",
        supervisor=session.get("supervisor"),
        supervisor_nombre=supervisor_nombre,
        total_buses=total_buses,
        total_empleados=total_empleados,
        choferes_count=choferes_count,
        cobradores_count=cobradores_count,
        total_recaudado=total_recaudado,
        total_rutas=total_rutas,
        total_incidencias=total_incidencias,
        buses_por_ruta=buses_por_ruta,
        incidencias_recientes=incidencias_recientes
        , route_id=session.get('route_id'), route_letra=session.get('route_letra')
    )


# Rutas del panel supervisor
@app.route("/supervisor/buses")
def supervisor_buses():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT b.*, r.letra AS ruta_letra, e.nombre AS encargado_nombre, e.apellido AS encargado_apellido
            FROM bus b
            LEFT JOIN ruta r ON b.id_ruta = r.id_ruta
            LEFT JOIN empleado e ON b.id_empleado = e.id_empleado
            WHERE b.id_ruta=%s
            ORDER BY b.id_bus
            """, (session['route_id'],)
        )
    else:
        cursor.execute(
            """
            SELECT b.*, r.letra AS ruta_letra, e.nombre AS encargado_nombre, e.apellido AS encargado_apellido
            FROM bus b
            LEFT JOIN ruta r ON b.id_ruta = r.id_ruta
            LEFT JOIN empleado e ON b.id_empleado = e.id_empleado
            ORDER BY b.id_bus
            """
        )
    buses = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/buses.html", supervisor=session["supervisor"], buses=buses)


@app.route("/admin_buses")
def admin_buses():
    if "supervisor" not in session:
        return redirect("/login")
    
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Filtrar por ruta según supervisor
    if session.get('route_id'):
        cursor.execute("""
            SELECT 
                b.id_bus, 
                b.placa, 
                b.modelo, 
                b.marca, 
                b.año_fabricacion,
                b.color, 
                b.ultima_revision,
                b.id_ruta,                     -- ESTA LÍNEA ES LA CLAVE
                r.letra AS ruta_letra,
                e.nombre AS encargado_nombre, 
                e.apellido AS encargado_apellido
            FROM bus b
            LEFT JOIN ruta r ON b.id_ruta = r.id_ruta
            LEFT JOIN empleado e ON b.id_empleado = e.id_empleado
            WHERE b.id_ruta=%s
            ORDER BY b.id_bus
        """, (session['route_id'],))
    else:
        cursor.execute("""
            SELECT 
                b.id_bus, 
                b.placa, 
                b.modelo, 
                b.marca, 
                b.año_fabricacion,
                b.color, 
                b.ultima_revision,
                b.id_ruta,                     -- IGUALMENTE SE AGREGA AQUÍ
                r.letra AS ruta_letra,
                e.nombre AS encargado_nombre, 
                e.apellido AS encargado_apellido
            FROM bus b
            LEFT JOIN ruta r ON b.id_ruta = r.id_ruta
            LEFT JOIN empleado e ON b.id_empleado = e.id_empleado
            ORDER BY b.id_bus
        """)

    buses = cursor.fetchall()

    # Cargar rutas disponibles (para el select)
    cursor.execute("SELECT id_ruta, letra FROM ruta ORDER BY letra")
    rutas = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("supervisor/admin_buses.html",
                           supervisor=session["supervisor"],
                           buses=buses,
                           rutas=rutas)



@app.route("/admin_buses/update", methods=["POST"])
def update_bus():
    if "supervisor" not in session:
        return redirect("/login")

    id_bus = request.form.get("id_bus")
    placa = request.form.get("placa")
    modelo = request.form.get("modelo")
    marca = request.form.get("marca")
    año = request.form.get("año_fabricacion")
    color = request.form.get("color")
    revision = request.form.get("ultima_revision")
    id_ruta = request.form.get("id_ruta")



    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE bus SET 
            placa=%s,
            modelo=%s,
            marca=%s,
            año_fabricacion=%s,
            color=%s,
            ultima_revision=%s
            id_ruta=%s

        WHERE id_bus=%s
    """, (placa, modelo, marca, año, color, revision, id_bus))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/admin_buses")

@app.route("/admin_buses/update_all", methods=["POST"])
def update_all_buses():
    if "supervisor" not in session:
        return redirect("/login")

    ids = request.form.getlist("id_bus[]")
    placas = request.form.getlist("placa[]")
    modelos = request.form.getlist("modelo[]")
    marcas = request.form.getlist("marca[]")
    años = request.form.getlist("año_fabricacion[]")
    colores = request.form.getlist("color[]")
    revisiones = request.form.getlist("ultima_revision[]")
    rutas = request.form.getlist("id_ruta[]") 

    conn = get_connection()
    cursor = conn.cursor()

    for i in range(len(ids)):
        cursor.execute("""
            UPDATE bus SET
                placa=%s,
                modelo=%s,
                marca=%s,
                año_fabricacion=%s,
                color=%s,
                ultima_revision=%s,
                id_ruta=%s
            WHERE id_bus=%s
        """, (placas[i], modelos[i], marcas[i], años[i], colores[i], revisiones[i], rutas[i], ids[i]))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/supervisor/buses")


@app.route("/admin_buses/delete/<int:id_bus>", methods=["POST"])
def admin_buses_delete(id_bus):
    if "supervisor" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM bus WHERE id_bus = %s", (id_bus,))
        conn.commit()
        flash("Bus eliminado correctamente", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error al eliminar el bus: {e}", "danger")

    cursor.close()
    conn.close()

    return redirect("/admin_buses")

@app.route("/admin_buses/nuevo", methods=["GET"])
def admin_buses_nuevo_get():
    if "supervisor" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Rutas disponibles
    cursor.execute("SELECT * FROM ruta ORDER BY letra")
    rutas = cursor.fetchall()

    # Empleados disponibles
    cursor.execute("SELECT id_empleado, nombre, apellido FROM empleado ORDER BY nombre")
    empleados = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("supervisor/nuevo_bus.html", rutas=rutas, empleados=empleados)

@app.route("/admin_buses/nuevo", methods=["POST"])
def admin_buses_nuevo_post():
    if "supervisor" not in session:
        return redirect("/login")

    placa = request.form.get("placa")
    modelo = request.form.get("modelo")
    marca = request.form.get("marca")
    año = request.form.get("año_fabricacion")
    color = request.form.get("color")
    revision = request.form.get("ultima_revision")
    id_ruta = request.form.get("id_ruta")
    id_empleado = request.form.get("id_empleado")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO bus (placa, modelo, marca, año_fabricacion, color, ultima_revision, id_ruta, id_empleado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (placa, modelo, marca, año, color, revision, id_ruta, id_empleado))
        
        conn.commit()
        flash("Bus agregado correctamente", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    cursor.close()
    conn.close()

    return redirect("/admin_buses")

@app.route("/admin_buses/export")
def export_buses_csv():
    if "supervisor" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    #   CONSULTA FILTRADA SOLO DE TU RUTA

    sql = """
        SELECT b.id_bus, b.placa, b.modelo, b.marca, b.año_fabricacion,
               b.color, b.ultima_revision, r.letra AS ruta_letra,
               e.nombre AS encargado_nombre, e.apellido AS encargado_apellido
        FROM bus b
        LEFT JOIN ruta r ON b.id_ruta = r.id_ruta
        LEFT JOIN empleado e ON b.id_empleado = e.id_empleado
        {filtro}
        ORDER BY b.id_bus
    """

    filtro = ""
    params = []

    if session.get("route_id"):
        filtro = "WHERE b.id_ruta=%s"
        params = [session["route_id"]]

    cursor.execute(sql.format(filtro=filtro), params)
    buses = cursor.fetchall()
    #   OBTENER CREATE TABLE REAL

    cursor.execute("SHOW CREATE TABLE bus")
    create_data = cursor.fetchone()
    create_sql = create_data["Create Table"]

    cursor.close()
    conn.close()
    #   GENERAR CSV

    import csv
    import io
    from flask import send_file

    output = io.StringIO()
    writer = csv.writer(output)


    writer.writerow(["=== DATOS DE LOS BUSES SUPERVISADOS ==="])
    writer.writerow([])

    if buses:
        # Cabeceras
        writer.writerow(buses[0].keys())
        # Filas
        for row in buses:
            writer.writerow(row.values())
    else:
        writer.writerow(["No tienes buses en esta ruta"])

    writer.writerow([])
    writer.writerow([])

    writer.writerow(["=== SENTENCIA SQL PARA CREAR TABLA BUS ==="])
    writer.writerow([create_sql])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        as_attachment=True,
        download_name="buses.csv",
        mimetype="text/csv"
    )











@app.route("/supervisor/caja")
def supervisor_caja():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT rc.*, e.nombre AS empleado_nombre, e.apellido AS empleado_apellido, r.letra AS ruta_letra
            FROM regstro_caja rc
            LEFT JOIN empleado e ON rc.id_empleado = e.id_empleado
            LEFT JOIN ruta r ON rc.id_ruta = r.id_ruta
            WHERE rc.id_ruta=%s
            ORDER BY rc.fecha_recaudacion DESC
            """, (session['route_id'],)
        )
    else:
        cursor.execute(
            """
            SELECT rc.*, e.nombre AS empleado_nombre, e.apellido AS empleado_apellido, r.letra AS ruta_letra
            FROM regstro_caja rc
            LEFT JOIN empleado e ON rc.id_empleado = e.id_empleado
            LEFT JOIN ruta r ON rc.id_ruta = r.id_ruta
            ORDER BY rc.fecha_recaudacion DESC
            """
        )
    cajas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/caja.html", supervisor=session["supervisor"], cajas=cajas)



@app.route("/supervisor/empleados")
def supervisor_empleados():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT DISTINCT e.*, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida
            FROM empleado e
            LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado
            LEFT JOIN horario h ON he.id_horario = h.id_horario
            LEFT JOIN bus b ON e.id_empleado = b.id_empleado
            LEFT JOIN regstro_caja rc ON e.id_empleado = rc.id_empleado
            WHERE (b.id_ruta=%s OR rc.id_ruta=%s)
            ORDER BY e.id_empleado
            """, (session['route_id'], session['route_id'])
        )
    else:
        cursor.execute(
            """
            SELECT e.*, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida
            FROM empleado e
            LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado
            LEFT JOIN horario h ON he.id_horario = h.id_horario
            ORDER BY e.id_empleado
            """
        )
    empleados = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/empleados.html", supervisor=session["supervisor"], empleados=empleados)



@app.route("/supervisor/empleados/choferes")
def supervisor_choferes():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT DISTINCT c.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida
            FROM chofer c
            LEFT JOIN empleado e ON c.id_empleado = e.id_empleado
            LEFT JOIN bus b ON b.id_empleado = c.id_empleado
            LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado
            LEFT JOIN horario h ON he.id_horario = h.id_horario
            WHERE b.id_ruta=%s
            ORDER BY c.id_empleado
            """, (session['route_id'],)
        )
    else:
        cursor.execute(
            """
            SELECT c.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida
            FROM chofer c
            LEFT JOIN empleado e ON c.id_empleado = e.id_empleado
            LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado
            LEFT JOIN horario h ON he.id_horario = h.id_horario
            ORDER BY c.id_empleado
            """
        )
    choferes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/choferes.html", supervisor=session["supervisor"], choferes=choferes)



@app.route("/supervisor/empleados/cobradores")
def supervisor_cobradores():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT DISTINCT cb.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida
            FROM cobrador cb
            LEFT JOIN empleado e ON cb.id_empleado = e.id_empleado
            LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado
            LEFT JOIN horario h ON he.id_horario = h.id_horario
            LEFT JOIN bus b ON b.id_empleado = cb.id_empleado
            LEFT JOIN regstro_caja rc ON rc.id_empleado = cb.id_empleado
            WHERE (b.id_ruta=%s OR rc.id_ruta=%s)
            ORDER BY cb.id_empleado
            """, (session['route_id'], session['route_id'])
        )
    else:
        cursor.execute(
            """
            SELECT cb.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida
            FROM cobrador cb
            LEFT JOIN empleado e ON cb.id_empleado = e.id_empleado
            LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado
            LEFT JOIN horario h ON he.id_horario = h.id_horario
            ORDER BY cb.id_empleado
            """
        )
    cobradores = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/cobradores.html", supervisor=session["supervisor"], cobradores=cobradores)



@app.route("/supervisor/incidencias")
def supervisor_incidencias():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT i.* 
            FROM incdncia_oprtva i
            LEFT JOIN bus b ON i.id_bus=b.id_bus
            WHERE b.id_ruta=%s
            ORDER BY i.fecha DESC
            """, (session['route_id'],)
        )
    else:
        cursor.execute("SELECT * FROM incdncia_oprtva ORDER BY fecha DESC")
    incidencias = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/incidencias.html", supervisor=session["supervisor"], incidencias=incidencias)



@app.route("/supervisor/rutas")
def supervisor_rutas():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            """
            SELECT r.*, COUNT(p.id_paradero) AS paraderos
            FROM ruta r
            LEFT JOIN paradero p ON r.id_ruta = p.id_ruta
            WHERE r.id_ruta=%s
            GROUP BY r.id_ruta
            """, (session['route_id'],)
        )
    else:
        cursor.execute(
            """
            SELECT r.*, COUNT(p.id_paradero) AS paraderos
            FROM ruta r
            LEFT JOIN paradero p ON r.id_ruta = p.id_ruta
            GROUP BY r.id_ruta
            """
        )
    rutas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("supervisor/rutas_admin.html", supervisor=session["supervisor"], rutas=rutas)


# Cerrar sesiónnn
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")




from datetime import datetime

ALLOWED_ENTITY_TABLES = {
    "bus": "bus",
    "empleado": "empleado",
    "ruta": "ruta",
    "incidencia": "incdncia_oprtva",
    "caja": "regstro_caja"
}

ALLOWED_SQL_START = ("UPDATE", "DELETE", "INSERT")
FORBIDDEN_WORDS = ("DROP", "ALTER", "TRUNCATE", "CREATE", "EXEC", ";--")

PK_MAP = {
    "bus": "id_bus",
    "empleado": "id_empleado",
    "ruta": "id_ruta",
    "incidencia": "id_incdncia_oprtva",
    "caja": "id_regstro_caja"
}


@app.route('/ejecutar_sql', methods=['POST'])
def ejecutar_sql():
    if "supervisor" not in session:
        return redirect("/login")

    sql = request.form.get("sql")
    mensaje = ""
    resultados = []

    sql_upper = sql.strip().upper()

    # Validaciones de seguridad
    if not sql_upper.startswith(("SELECT", "UPDATE", "DELETE", "INSERT")):
        return "Solo puedes ejecutar SELECT, UPDATE, DELETE o INSERT"
    if any(bad in sql_upper for bad in ("DROP", "ALTER", "TRUNCATE", "CREATE", "EXEC", ";--")):
        return "Comando SQL bloqueado por seguridad"

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)


        tablas_filtradas = ["BUS", "EMPLEADO", "CHOFER", "COBRADOR"]

        ruta_id = session.get("route_id")
        agregar_filtro = False

        # Solo si es SELECT y hay ruta definida
        if sql_upper.startswith("SELECT") and ruta_id:
            for tabla in tablas_filtradas:
                if f"FROM {tabla}" in sql_upper:
                    agregar_filtro = True
                    break
            if agregar_filtro:
                if "WHERE" in sql_upper:
                    sql += " AND id_ruta = %s"
                else:
                    sql += " WHERE id_ruta = %s"
                cursor.execute(sql, (ruta_id,))
            else:
                cursor.execute(sql)
        else:

            cursor.execute(sql)
            if sql_upper.startswith(("UPDATE", "DELETE", "INSERT")):
               
                conn.commit()

        if sql_upper.startswith("SELECT"):
            resultados = cursor.fetchall()
            mensaje = f"{len(resultados)} registros encontrados."
        else:
            mensaje = "Consulta ejecutada correctamente."

    except Exception as e:
        conn.rollback()
        mensaje = f"Error al ejecutar SQL: {str(e)}"
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "supervisor/editar_entidad.html",
        supervisor=session["supervisor"],
        entidad="bus", 
        registro=None,
        pk=None,
        mensaje=mensaje,
        resultados=resultados
    )


@app.route("/supervisor/editar/<entidades>/<int:registro_id>", methods=["GET", "POST"])
def editar_entidades(entidades, registro_id):
    """
    Permite editar 1, 2 o 3 entidades juntas mediante SQL puro.
    `entidades` puede ser:
        - "bus"
        - "empleado,bus"
        - "empleado,bus,regstro_caja"
    `registro_id` es el ID principal de la primera entidad.
    """
    if "supervisor" not in session:
        return redirect("/login")

    # Separar entidades
    lista_entidades = [e.strip() for e in entidades.split(",")]

    # Validar que todas existan
    for e in lista_entidades:
        if e not in ALLOWED_ENTITY_TABLES:
            return f"Entidad no válida: {e}"

    # Obtenemos la tabla principal
    tabla_principal = ALLOWED_ENTITY_TABLES[lista_entidades[0]]
    pk_principal = PK_MAP[lista_entidades[0]]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Obtener registro principal
    cursor.execute(f"SELECT * FROM {tabla_principal} WHERE {pk_principal} = %s", (registro_id,))
    registro = cursor.fetchone()

    if request.method == "POST":
        sql = request.form["sql"]
        sql_upper = sql.upper()

        # Validaciones de seguridad
        if not sql_upper.startswith(ALLOWED_SQL_START):
            return "Solo puedes ejecutar UPDATE, DELETE o INSERT"
        if any(bad in sql_upper for bad in FORBIDDEN_WORDS):
            return "Comando SQL bloqueado por seguridad"

        # Ejecutar SQL
        try:
            cursor2 = conn.cursor()
            cursor2.execute(sql)
            conn.commit()
            cursor2.close()
            mensaje = "Consulta ejecutada correctamente."
        except Exception as e:
            conn.rollback()
            mensaje = f"Error SQL: {str(e)}"

        cursor.close()
        conn.close()
        return mensaje
    # Si es GET, mostramos el registro y la lista de entidades
    cursor.close()
    conn.close()
    return render_template(
        "supervisor/editar_entidad.html",
        entidades=lista_entidades,
        registro=registro,
        pk=pk_principal
    )

    
    
if __name__ == "__main__":
    app.run(debug=True)