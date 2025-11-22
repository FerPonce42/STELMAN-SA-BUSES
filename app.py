from flask import Flask, render_template, request, redirect, session
from config import get_connection
import re

app = Flask(__name__)
app.secret_key = "clave_segura_cualquiera"

# Página pública principal
@app.route("/")
def index():
    # Intentar obtener buses y horarios desde la base de datos; si falla, pasar listas vacías
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
        usuario = request.form["usuario"]
        clave = request.form["clave"]

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # En la base de datos el volcado usa columnas USUARIO y CONTRASENA
        cursor.execute("SELECT * FROM supervisor WHERE USUARIO=%s AND CONTRASENA=%s", (usuario, clave))
        supervisor = cursor.fetchone()
        cursor.close()
        conn.close()

        if supervisor:
            # Guardar datos de supervisor en sesión
            session["supervisor"] = supervisor

            # Intentar asociar al supervisor con una ruta concreta
            route_id = None
            route_letra = None
            area = supervisor.get('area_encargada') if isinstance(supervisor, dict) else None
            if area:
                # Buscar una letra de ruta aislada en el texto (ej. 'Ruta S' -> 'S')
                m = re.search(r"\b([FSNM])\b", area, re.IGNORECASE)
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

            # Guardar filtro de ruta en sesión (si se detectó)
            if route_id:
                session['route_id'] = route_id
                session['route_letra'] = route_letra
                app.logger.info(f"Supervisor {supervisor.get('id_empleado')} assigned to route_id={route_id} letra={route_letra}")
            else:
                session.pop('route_id', None)
                session.pop('route_letra', None)
                app.logger.info(f"Supervisor {supervisor.get('id_empleado')} has no route assignment parsed from area_encargada={area}")
            return redirect("/dashboard")
        else:
            # Mostrar la plantilla de login con mensaje de error
            return render_template("auth/login.html", error="Credenciales incorrectas")

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
    # Conteo de buses por ruta (si route_id existe, devolver solo esa ruta)
    if session.get('route_id'):
        cursor.execute("SELECT r.letra AS ruta, COUNT(b.id_bus) AS buses_count FROM ruta r LEFT JOIN bus b ON r.id_ruta = b.id_ruta WHERE r.id_ruta=%s GROUP BY r.id_ruta ORDER BY r.letra", (session['route_id'],))
    else:
        cursor.execute("SELECT r.letra AS ruta, COUNT(b.id_bus) AS buses_count FROM ruta r LEFT JOIN bus b ON r.id_ruta = b.id_ruta GROUP BY r.id_ruta ORDER BY r.letra")
    buses_por_ruta = cursor.fetchall()

    # Incidencias recientes
    # Incidencias recientes (si route filter exists, filtrar por bus->ruta)
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


@app.route("/supervisor/caja")
def supervisor_caja():
    if "supervisor" not in session:
        return redirect("/login")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if session.get('route_id'):
        cursor.execute(
            "SELECT rc.*, e.nombre AS empleado_nombre, e.apellido AS empleado_apellido, r.letra AS ruta_letra "
            "FROM regstro_caja rc "
            "LEFT JOIN empleado e ON rc.id_empleado = e.id_empleado "
            "LEFT JOIN ruta r ON rc.id_ruta = r.id_ruta "
            "WHERE rc.id_ruta=%s "
            "ORDER BY rc.fecha_recaudacion DESC", (session['route_id'],)
        )
    else:
        cursor.execute(
            "SELECT rc.*, e.nombre AS empleado_nombre, e.apellido AS empleado_apellido, r.letra AS ruta_letra "
            "FROM regstro_caja rc "
            "LEFT JOIN empleado e ON rc.id_empleado = e.id_empleado "
            "LEFT JOIN ruta r ON rc.id_ruta = r.id_ruta "
            "ORDER BY rc.fecha_recaudacion DESC"
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
            "SELECT DISTINCT e.*, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida "
            "FROM empleado e "
            "LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado "
            "LEFT JOIN horario h ON he.id_horario = h.id_horario "
            "LEFT JOIN bus b ON e.id_empleado = b.id_empleado "
            "LEFT JOIN regstro_caja rc ON e.id_empleado = rc.id_empleado "
            "WHERE (b.id_ruta=%s OR rc.id_ruta=%s) "
            "ORDER BY e.id_empleado", (session['route_id'], session['route_id'])
        )
    else:
        cursor.execute(
            "SELECT e.*, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida "
            "FROM empleado e "
            "LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado "
            "LEFT JOIN horario h ON he.id_horario = h.id_horario "
            "ORDER BY e.id_empleado"
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
            "SELECT DISTINCT c.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida "
            "FROM chofer c "
            "LEFT JOIN empleado e ON c.id_empleado = e.id_empleado "
            "LEFT JOIN bus b ON b.id_empleado = c.id_empleado "
            "LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado "
            "LEFT JOIN horario h ON he.id_horario = h.id_horario "
            "WHERE b.id_ruta=%s "
            "ORDER BY c.id_empleado", (session['route_id'],)
        )
    else:
        cursor.execute(
            "SELECT c.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida "
            "FROM chofer c "
            "LEFT JOIN empleado e ON c.id_empleado = e.id_empleado "
            "LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado "
            "LEFT JOIN horario h ON he.id_horario = h.id_horario "
            "ORDER BY c.id_empleado"
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
    # Mostrar todos los cobradores (sin filtrar por ruta)
    cursor.execute(
        "SELECT cb.*, e.nombre, e.apellido, e.dni, h.dia_semana AS horario_dia, h.hora_inicio AS horario_inicio, h.hora_salida AS horario_salida FROM cobrador cb "
        "LEFT JOIN empleado e ON cb.id_empleado = e.id_empleado "
        "LEFT JOIN hrrio_empleado he ON e.id_empleado = he.id_empleado "
        "LEFT JOIN horario h ON he.id_horario = h.id_horario "
        "ORDER BY cb.id_empleado"
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
    # la tabla en el volcado se llama `incdncia_oprtva`
    if session.get('route_id'):
        cursor.execute("SELECT i.* FROM incdncia_oprtva i LEFT JOIN bus b ON i.id_bus=b.id_bus WHERE b.id_ruta=%s ORDER BY i.fecha DESC", (session['route_id'],))
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
            "SELECT r.*, COUNT(p.id_paradero) AS paraderos "
            "FROM ruta r LEFT JOIN paradero p ON r.id_ruta = p.id_ruta "
            "WHERE r.id_ruta=%s "
            "GROUP BY r.id_ruta", (session['route_id'],)
        )
    else:
        cursor.execute(
            "SELECT r.*, COUNT(p.id_paradero) AS paraderos "
            "FROM ruta r LEFT JOIN paradero p ON r.id_ruta = p.id_ruta "
            "GROUP BY r.id_ruta"
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

if __name__ == "__main__":
    app.run(debug=True)
